import json
from datetime import datetime, time as dtime
from decimal import Decimal, InvalidOperation

from django.contrib.auth import authenticate
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .bracket import (
    _ordinal,
    get_de_placements,
    get_round_robin_standings,
    get_se_placements,
    placement_payout,
)
from .models import (
    ApiToken,
    GAME_CHOICES,
    FORMAT_CHOICES,
    Payout,
    Player,
    Tournament,
    TournamentEntry,
    Venue,
)


def _authenticate(request):
    """Resolve `Authorization: Token <hex>` to a User, or return None."""
    header = request.META.get('HTTP_AUTHORIZATION', '')
    prefix = 'Token '
    if not header.startswith(prefix):
        return None
    key = header[len(prefix):].strip()
    if not key:
        return None
    try:
        token = ApiToken.objects.select_related('user').get(key=key)
    except ApiToken.DoesNotExist:
        return None
    token.last_used_at = timezone.now()
    token.save(update_fields=['last_used_at'])
    return token.user


def _err(message, status=400):
    return JsonResponse({'error': message}, status=status)


def _parse_decimal(value, field):
    if value is None or value == '':
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise ValueError(f'{field} must be a number')


VALID_GAMES = {c[0] for c in GAME_CHOICES}
VALID_FORMATS = {c[0] for c in FORMAT_CHOICES}
VALID_PAYOUT_TYPES = {c[0] for c in Payout.PAYOUT_TYPES}


@csrf_exempt
@require_POST
def create_tournament(request):
    user = _authenticate(request)
    if not user:
        return _err('Invalid or missing API token. Send `Authorization: Token <hex>`.', status=401)

    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return _err('Request body must be valid JSON.')
    if not isinstance(data, dict):
        return _err('Request body must be a JSON object.')

    name = (data.get('name') or '').strip()
    if not name:
        return _err('`name` is required.')

    game_type = data.get('game_type', '8ball')
    if game_type not in VALID_GAMES:
        return _err(f'`game_type` must be one of: {sorted(VALID_GAMES)}.')

    fmt = data.get('format', 'single_elim')
    if fmt not in VALID_FORMATS:
        return _err(f'`format` must be one of: {sorted(VALID_FORMATS)}.')

    date_str = data.get('date')
    date_value = None
    if date_str:
        try:
            parsed = datetime.strptime(date_str, '%Y-%m-%d')
        except (ValueError, TypeError):
            return _err('`date` must be in YYYY-MM-DD format.')
        date_value = datetime.combine(parsed.date(), dtime(12, 0))

    try:
        entry_fee = _parse_decimal(data.get('entry_fee'), 'entry_fee')
        added_money = _parse_decimal(data.get('added_money'), 'added_money') or Decimal('0')
    except ValueError as e:
        return _err(str(e))

    venue = None
    venue_id = data.get('venue_id')
    if venue_id is not None:
        try:
            venue = Venue.objects.get(pk=venue_id)
        except Venue.DoesNotExist:
            return _err(f'Venue {venue_id} not found.')

    teams = data.get('teams', [])
    if not isinstance(teams, list):
        return _err('`teams` must be a list.')

    cleaned_teams = []
    seen = set()
    for i, item in enumerate(teams):
        if isinstance(item, str):
            tname, email, phone = item.strip(), '', ''
        elif isinstance(item, dict):
            tname = (item.get('name') or '').strip()
            email = item.get('email') or ''
            phone = item.get('phone') or ''
        else:
            return _err(f'teams[{i}] must be a string or object.')
        if not tname:
            return _err(f'teams[{i}] has no name.')
        key = tname.lower()
        if key in seen:
            return _err(f'Duplicate team name: {tname!r}.')
        seen.add(key)
        cleaned_teams.append({'name': tname, 'email': email, 'phone': phone})

    notes = data.get('notes', '') or ''

    with transaction.atomic():
        tournament = Tournament.objects.create(
            name=name,
            game_type=game_type,
            format=fmt,
            date=date_value,
            entry_fee=entry_fee,
            added_money=added_money,
            venue=venue,
            notes=notes,
            created_by=user,
        )

        entries_out = []
        for i, t in enumerate(cleaned_teams):
            player, _created = Player.objects.get_or_create(
                name=t['name'],
                created_by=user,
                defaults={'email': t['email'], 'phone': t['phone']},
            )
            entry = TournamentEntry.objects.create(
                tournament=tournament,
                player=player,
                seed=i + 1,
            )
            entries_out.append({
                'id': entry.id,
                'name': player.name,
                'seed': entry.seed,
            })

    return JsonResponse({
        'id': tournament.id,
        'name': tournament.name,
        'game_type': tournament.game_type,
        'format': tournament.format,
        'status': tournament.status,
        'entries': entries_out,
        'url': request.build_absolute_uri(f'/tournaments/{tournament.id}/'),
    }, status=201)


@csrf_exempt
@require_POST
def add_payout(request, pk):
    user = _authenticate(request)
    if not user:
        return _err('Invalid or missing API token. Send `Authorization: Token <hex>`.', status=401)

    try:
        tournament = Tournament.objects.get(pk=pk, created_by=user)
    except Tournament.DoesNotExist:
        return _err(f'Tournament {pk} not found.', status=404)

    if tournament.status == 'completed':
        return _err('Cannot edit payouts on a completed tournament.')

    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return _err('Request body must be valid JSON.')
    if not isinstance(data, dict):
        return _err('Request body must be a JSON object.')

    place = data.get('place')
    try:
        place = int(place)
        if place < 1:
            raise ValueError
    except (TypeError, ValueError):
        return _err('`place` must be a positive integer.')

    payout_type = data.get('payout_type')
    if payout_type not in VALID_PAYOUT_TYPES:
        return _err(f'`payout_type` must be one of: {sorted(VALID_PAYOUT_TYPES)}.')

    try:
        amount = _parse_decimal(data.get('amount'), 'amount')
    except ValueError as e:
        return _err(str(e))
    if amount is None or amount < 0:
        return _err('`amount` is required and cannot be negative.')

    if Payout.objects.filter(tournament=tournament, place=place).exists():
        return _err(f'A payout for place #{place} already exists.', status=409)

    payout = Payout.objects.create(
        tournament=tournament,
        place=place,
        payout_type=payout_type,
        amount=amount,
    )

    return JsonResponse({
        'id': payout.id,
        'tournament_id': tournament.id,
        'place': payout.place,
        'payout_type': payout.payout_type,
        'amount': str(payout.amount),
    }, status=201)


@csrf_exempt
@require_POST
def obtain_token(request):
    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return _err('Request body must be valid JSON.')
    if not isinstance(data, dict):
        return _err('Request body must be a JSON object.')

    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    if not username or not password:
        return _err('`username` and `password` are required.')

    user = authenticate(request, username=username, password=password)
    if user is None:
        return _err('Invalid credentials.', status=401)

    token = ApiToken.objects.filter(user=user).first()
    if token is None:
        token = ApiToken.generate_for(user)

    return JsonResponse({'token': token.key})


def _entry_json(entry):
    if entry is None:
        return None
    return {'id': entry.id, 'name': entry.player.name, 'seed': entry.seed}


def _money(value):
    return None if value is None else f'{value:.2f}'


def tournament_placements(tournament):
    """Final placements as (label, [entries], start_place, per-player payout),
    whatever the format. Round robins place every entry by the standings;
    brackets place only the champion and the eliminated."""
    payout_map = tournament.payout_amounts()
    if tournament.format == 'round_robin':
        rows = []
        for i, row in enumerate(get_round_robin_standings(tournament), start=1):
            rows.append((_ordinal(i), [row['entry']], i, payout_map.get(i)))
        return rows
    if tournament.format == 'double_elim':
        placements = get_de_placements(tournament)
    else:
        placements = get_se_placements(tournament)
    return [
        (label, entries, start_place, placement_payout(payout_map, start_place, len(entries)))
        for label, entries, start_place in placements
    ]


@require_GET
def tournament_results(request, pk):
    """Public, read-only JSON of a tournament: entries, matches and final
    placements with payouts. The bracket page is public, so this is too. It
    exists so a league site can import an end-of-season tournament's results."""
    try:
        tournament = Tournament.objects.select_related('venue').get(pk=pk)
    except Tournament.DoesNotExist:
        return _err(f'Tournament {pk} not found.', status=404)

    entries = list(tournament.entries.select_related('player').order_by('seed'))
    matches = list(
        tournament.matches.select_related(
            'player1__player', 'player2__player', 'winner__player',
        ).order_by('bracket', 'round_number', 'match_number')
    )

    return JsonResponse({
        'id': tournament.id,
        'name': tournament.name,
        'game_type': tournament.game_type,
        'format': tournament.format,
        'status': tournament.status,
        'date': tournament.date.date().isoformat() if tournament.date else None,
        'venue': tournament.venue.name if tournament.venue else None,
        'entry_fee': _money(tournament.entry_fee),
        'added_money': _money(tournament.added_money),
        'total_pot': _money(tournament.total_pot()),
        'url': request.build_absolute_uri(f'/tournaments/{tournament.id}/bracket/'),
        'entries': [_entry_json(entry) for entry in entries],
        'placements': [
            {
                'label': label,
                'place': start_place,
                'entries': [_entry_json(entry) for entry in placed],
                'payout': _money(payout),
            }
            for label, placed, start_place, payout in tournament_placements(tournament)
        ],
        'matches': [
            {
                'bracket': match.bracket,
                'round': match.round_number,
                'match': match.match_number,
                'player1': _entry_json(match.player1),
                'player2': _entry_json(match.player2),
                'winner': _entry_json(match.winner),
                'is_bye': match.is_bye,
            }
            for match in matches
        ],
    })
