from django.contrib.auth.models import User

from tournaments.models import Player, Tournament, TournamentEntry


def make_user(username='owner', password='pass12345'):
    return User.objects.create_user(username=username, password=password)


def make_tournament(user, name='Test Open', fmt='single_elim', status='pending', **kwargs):
    return Tournament.objects.create(
        name=name,
        game_type=kwargs.pop('game_type', '8ball'),
        format=fmt,
        created_by=user,
        status=status,
        **kwargs,
    )


def add_players(tournament, user, count):
    """Create `count` players and enter them seeded 1..count."""
    entries = []
    for i in range(1, count + 1):
        player = Player.objects.create(name=f'Player {i}', created_by=user)
        entries.append(
            TournamentEntry.objects.create(tournament=tournament, player=player, seed=i)
        )
    return entries


def win(match, entry):
    """Record a single-/round-robin result directly via bracket helpers."""
    from tournaments.bracket import record_result

    record_result(match, entry)


def get_match(tournament, bracket, round_number, match_number):
    return tournament.matches.get(
        bracket=bracket, round_number=round_number, match_number=match_number
    )
