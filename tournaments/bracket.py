import math


def _bracket_positions(bracket_size):
    """
    Returns seed positions in bracket slot order so that the top seed can
    only meet the 2nd seed in the final, top-half seeds stay in the top half, etc.
    e.g. bracket_size=8 → [1, 8, 4, 5, 3, 6, 2, 7]
    """
    if bracket_size == 2:
        return [1, 2]
    prev = _bracket_positions(bracket_size // 2)
    result = []
    for p in prev:
        result.append(p)
        result.append(bracket_size + 1 - p)
    return result


# ── Single Elimination ────────────────────────────────────────────────────────

def generate_single_elimination(tournament):
    from .models import Match

    tournament.matches.all().delete()

    entries = list(tournament.entries.order_by('seed'))
    n = len(entries)
    if n < 2:
        return

    num_rounds = math.ceil(math.log2(n))
    bracket_size = 2 ** num_rounds

    seed_map = {e.seed: e for e in entries}
    positions = _bracket_positions(bracket_size)
    # positions[i] is the seed that goes in slot i; None if seed > n (bye)
    slots = [seed_map.get(pos) for pos in positions]

    # ── Round 1 ──────────────────────────────────────────────────────────────
    round1_matches = []
    for i in range(0, bracket_size, 2):
        p1 = slots[i]
        p2 = slots[i + 1]
        is_bye = (p1 is None) or (p2 is None)
        winner = None
        if is_bye:
            winner = p1 or p2

        m = Match.objects.create(
            tournament=tournament,
            round_number=1,
            match_number=(i // 2) + 1,
            player1=p1,
            player2=p2,
            winner=winner,
            is_bye=is_bye,
        )
        round1_matches.append(m)

    # ── Later rounds (empty placeholders) ────────────────────────────────────
    prev_matches = round1_matches
    for rnd in range(2, num_rounds + 1):
        new_matches = []
        for i in range(0, len(prev_matches), 2):
            m = Match.objects.create(
                tournament=tournament,
                round_number=rnd,
                match_number=(i // 2) + 1,
            )
            new_matches.append(m)
        prev_matches = new_matches

    # ── Propagate bye winners into round 2 ───────────────────────────────────
    for m in round1_matches:
        if m.is_bye and m.winner:
            _advance_winner(tournament, m)


def _advance_winner(tournament, match):
    """Push match.winner into the appropriate slot of the next-round match."""
    from .models import Match

    next_round = match.round_number + 1
    next_match_number = math.ceil(match.match_number / 2)

    try:
        next_match = Match.objects.get(
            tournament=tournament,
            round_number=next_round,
            match_number=next_match_number,
        )
    except Match.DoesNotExist:
        return  # was the final

    if match.match_number % 2 == 1:
        next_match.player1 = match.winner
    else:
        next_match.player2 = match.winner

    # If both slots now filled by byes, auto-advance again
    if next_match.player1 and next_match.player2:
        next_match.save()
    elif next_match.player1 or next_match.player2:
        next_match.save()


def record_result(match, winner_entry):
    """Record a match result and advance the winner to the next round."""
    match.winner = winner_entry
    match.save()
    _advance_winner(match.tournament, match)

    # Check if tournament is complete
    tournament = match.tournament
    all_matches = tournament.matches.all()
    if all(m.winner is not None for m in all_matches):
        tournament.status = 'completed'
        tournament.save()


# ── Double Elimination ────────────────────────────────────────────────────────

def generate_double_elimination(tournament):
    from .models import Match

    tournament.matches.all().delete()

    entries = list(tournament.entries.order_by('seed'))
    n = len(entries)
    if n < 2:
        return

    wb_rounds = math.ceil(math.log2(n))
    bracket_size = 2 ** wb_rounds

    seed_map = {e.seed: e for e in entries}
    positions = _bracket_positions(bracket_size)
    slots = [seed_map.get(pos) for pos in positions]

    # ── Winners Bracket Round 1 ───────────────────────────────────────────────
    wb_r1_matches = []
    for i in range(0, bracket_size, 2):
        p1 = slots[i]
        p2 = slots[i + 1]
        is_bye = (p1 is None) or (p2 is None)
        winner = (p1 or p2) if is_bye else None
        m = Match.objects.create(
            tournament=tournament,
            bracket='winners',
            round_number=1,
            match_number=(i // 2) + 1,
            player1=p1,
            player2=p2,
            winner=winner,
            is_bye=is_bye,
        )
        wb_r1_matches.append(m)

    # ── Winners Bracket later rounds ─────────────────────────────────────────
    prev_wb = wb_r1_matches
    for rnd in range(2, wb_rounds + 1):
        new_wb = []
        for i in range(0, len(prev_wb), 2):
            m = Match.objects.create(
                tournament=tournament,
                bracket='winners',
                round_number=rnd,
                match_number=(i // 2) + 1,
            )
            new_wb.append(m)
        prev_wb = new_wb

    # ── Losers Bracket ────────────────────────────────────────────────────────
    # LB has 2*(wb_rounds - 1) rounds for bracket_size >= 4
    lb_rounds = 2 * (wb_rounds - 1)
    if lb_rounds > 0:
        # Each pair of LB rounds shares the same match count:
        # (LBR1, LBR2): B/4 matches, (LBR3, LBR4): B/8, ...
        count = bracket_size // 4
        for r in range(1, lb_rounds + 1):
            for m_num in range(1, count + 1):
                Match.objects.create(
                    tournament=tournament,
                    bracket='losers',
                    round_number=r,
                    match_number=m_num,
                )
            if r % 2 == 0:
                count //= 2

    # ── Grand Final ───────────────────────────────────────────────────────────
    Match.objects.create(
        tournament=tournament,
        bracket='grand_final',
        round_number=1,
        match_number=1,
    )

    # ── Propagate WBR1 byes ───────────────────────────────────────────────────
    for m in wb_r1_matches:
        if m.is_bye and m.winner:
            _de_advance(tournament, m)


def _get_wb_rounds(tournament):
    n = tournament.entries.count()
    return math.ceil(math.log2(max(n, 2)))


def _de_set_slot(tournament, bracket, round_num, match_num, player, slot):
    """Fill player into slot 1 or 2 of a match."""
    from .models import Match
    try:
        m = Match.objects.get(
            tournament=tournament,
            bracket=bracket,
            round_number=round_num,
            match_number=match_num,
        )
    except Match.DoesNotExist:
        return
    if slot == 1:
        m.player1 = player
    else:
        m.player2 = player
    m.save()


def _de_advance(tournament, match):
    """Route winner (and WB loser) after a double-elimination match result."""
    from .models import Match

    wb_rounds = _get_wb_rounds(tournament)
    lb_rounds = 2 * (wb_rounds - 1)

    loser = match.player2 if match.winner == match.player1 else match.player1

    if match.bracket == 'winners':
        # ── Route winner forward in WB or to Grand Final ──────────────────
        if match.round_number < wb_rounds:
            next_m = math.ceil(match.match_number / 2)
            slot = 1 if match.match_number % 2 == 1 else 2
            _de_set_slot(tournament, 'winners', match.round_number + 1, next_m, match.winner, slot)
        else:
            # WB Final winner → Grand Final player 1
            _de_set_slot(tournament, 'grand_final', 1, 1, match.winner, 1)

        # ── Route loser to LB (skip byes — no real loser) ────────────────
        if loser and not match.is_bye and lb_rounds > 0:
            if match.round_number == 1:
                # WBR1 losers pair up in LBR1
                lb_m = math.ceil(match.match_number / 2)
                lb_slot = 1 if match.match_number % 2 == 1 else 2
                _de_set_slot(tournament, 'losers', 1, lb_m, loser, lb_slot)
            else:
                # WBR(k) losers for k >= 2 → LBR(2k-2), same match number, slot 2
                lb_r = 2 * (match.round_number - 1)
                _de_set_slot(tournament, 'losers', lb_r, match.match_number, loser, 2)

    elif match.bracket == 'losers':
        if match.round_number < lb_rounds:
            next_r, next_m, slot = _lb_next_slot(match.round_number, match.match_number)
            _de_set_slot(tournament, 'losers', next_r, next_m, match.winner, slot)
        else:
            # LB Final winner → Grand Final player 2
            _de_set_slot(tournament, 'grand_final', 1, 1, match.winner, 2)

    elif match.bracket == 'grand_final':
        if match.round_number == 1:
            # Determine which side won:
            # p1 = WB side, p2 = LB side
            # If LB side (p2) wins → bracket reset
            if match.winner == match.player2:
                try:
                    Match.objects.get(
                        tournament=tournament,
                        bracket='grand_final',
                        round_number=2,
                        match_number=1,
                    )
                except Match.DoesNotExist:
                    Match.objects.create(
                        tournament=tournament,
                        bracket='grand_final',
                        round_number=2,
                        match_number=1,
                        player1=match.player1,
                        player2=match.player2,
                    )
        # round 2 (bracket reset) winner = champion; no further routing needed


def _lb_next_slot(r, m):
    """
    Return (next_round, next_match_num, slot) for a LB match winner.

    Odd LB rounds: winner goes to next round, same match number, slot 1.
    Even LB rounds: winner goes to next round, match ceil(m/2),
                    slot 1 if m is odd, slot 2 if m is even.
    """
    if r % 2 == 1:
        return r + 1, m, 1
    else:
        return r + 1, math.ceil(m / 2), (1 if m % 2 == 1 else 2)


def record_de_result(match, winner_entry):
    """Record a double-elimination match result and route players."""
    match.winner = winner_entry
    match.save()
    _de_advance(match.tournament, match)

    tournament = match.tournament
    if all(m.winner is not None for m in tournament.matches.all()):
        tournament.status = 'completed'
        tournament.save()


def get_de_data(tournament):
    """Return structured data for the double elimination bracket template."""
    from collections import defaultdict

    wb = defaultdict(list)
    lb = defaultdict(list)
    gf = []

    for match in tournament.matches.order_by('bracket', 'round_number', 'match_number'):
        if match.bracket == 'winners':
            wb[match.round_number].append(match)
        elif match.bracket == 'losers':
            lb[match.round_number].append(match)
        else:
            gf.append(match)

    wb_count = len(wb)
    lb_count = len(lb)

    wb_rounds = []
    for i in range(1, wb_count + 1):
        remaining = wb_count - i + 1
        if remaining == 1:
            label = 'WB Final'
        elif remaining == 2:
            label = 'WB Semis'
        elif remaining == 3:
            label = 'WB Quarters'
        else:
            label = f'WB Round {i}'
        wb_rounds.append((label, wb[i]))

    lb_rounds = [(f'LB Round {i}', lb[i]) for i in range(1, lb_count + 1)]

    return {
        'wb_rounds': wb_rounds,
        'lb_rounds': lb_rounds,
        'gf_matches': gf,
    }


# ── Round Robin ───────────────────────────────────────────────────────────────

def generate_round_robin(tournament):
    from .models import Match

    tournament.matches.all().delete()

    entries = list(tournament.entries.order_by('seed'))
    n = len(entries)
    if n < 2:
        return

    # Generate all pairs
    match_number = 1
    for i in range(n):
        for j in range(i + 1, n):
            Match.objects.create(
                tournament=tournament,
                round_number=1,
                match_number=match_number,
                player1=entries[i],
                player2=entries[j],
            )
            match_number += 1


def get_round_robin_standings(tournament):
    entries = list(tournament.entries.order_by('seed'))
    stats = {e.id: {'entry': e, 'wins': 0, 'losses': 0, 'played': 0} for e in entries}

    for match in tournament.matches.filter(winner__isnull=False):
        if match.player1_id:
            stats[match.player1_id]['played'] += 1
        if match.player2_id:
            stats[match.player2_id]['played'] += 1
        if match.winner_id:
            stats[match.winner_id]['wins'] += 1
            loser_id = match.player1_id if match.winner_id == match.player2_id else match.player2_id
            if loser_id and loser_id in stats:
                stats[loser_id]['losses'] += 1

    return sorted(stats.values(), key=lambda x: (-x['wins'], x['losses']))


def get_bracket_rounds(tournament):
    """Return matches grouped by round for bracket display."""
    from collections import defaultdict
    rounds = defaultdict(list)
    for match in tournament.matches.order_by('round_number', 'match_number'):
        rounds[match.round_number].append(match)
    return [rounds[r] for r in sorted(rounds.keys())]
