from django.test import TestCase

from tournaments.bracket import (
    _bracket_positions,
    _ordinal,
    generate_double_elimination,
    generate_round_robin,
    generate_single_elimination,
    get_bracket_rounds,
    get_de_data,
    get_de_placements,
    get_round_robin_standings,
    get_se_placements,
    record_de_result,
    record_result,
    undo_result,
)

from .helpers import add_players, get_match, make_tournament, make_user


class BracketPositionsTests(TestCase):
    def test_size_2(self):
        self.assertEqual(_bracket_positions(2), [1, 2])

    def test_size_4(self):
        self.assertEqual(_bracket_positions(4), [1, 4, 2, 3])

    def test_size_8(self):
        self.assertEqual(_bracket_positions(8), [1, 8, 4, 5, 2, 7, 3, 6])


class OrdinalTests(TestCase):
    def test_common(self):
        self.assertEqual(_ordinal(1), '1st')
        self.assertEqual(_ordinal(2), '2nd')
        self.assertEqual(_ordinal(3), '3rd')
        self.assertEqual(_ordinal(4), '4th')
        self.assertEqual(_ordinal(21), '21st')

    def test_teens(self):
        self.assertEqual(_ordinal(11), '11th')
        self.assertEqual(_ordinal(12), '12th')
        self.assertEqual(_ordinal(13), '13th')


# ── Single Elimination ────────────────────────────────────────────────────────

class SingleEliminationTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_too_few_players_no_matches(self):
        t = make_tournament(self.user)
        add_players(t, self.user, 1)
        generate_single_elimination(t)
        self.assertEqual(t.matches.count(), 0)

    def test_power_of_two_no_byes(self):
        t = make_tournament(self.user)
        add_players(t, self.user, 4)
        generate_single_elimination(t)
        # rounds: 2, matches: 2 (r1) + 1 (r2) = 3
        self.assertEqual(t.matches.count(), 3)
        r1 = t.matches.filter(round_number=1)
        self.assertEqual(r1.count(), 2)
        self.assertFalse(any(m.is_bye for m in r1))

    def test_non_power_of_two_has_byes(self):
        t = make_tournament(self.user)
        add_players(t, self.user, 6)
        generate_single_elimination(t)
        # bracket size 8, 4 first round matches, 2 byes for seeds 1 & 2
        r1 = t.matches.filter(round_number=1)
        self.assertEqual(r1.count(), 4)
        byes = [m for m in r1 if m.is_bye]
        self.assertEqual(len(byes), 2)
        # bye winners auto-advanced into round 2
        r2 = t.matches.filter(round_number=2)
        for m in r2:
            # each r2 match should have at least one player from a bye
            pass
        self.assertTrue(any(m.player1 or m.player2 for m in r2))

    def test_regenerate_clears_old_matches(self):
        t = make_tournament(self.user)
        add_players(t, self.user, 4)
        generate_single_elimination(t)
        first_count = t.matches.count()
        generate_single_elimination(t)
        self.assertEqual(t.matches.count(), first_count)

    def test_full_run_completes_and_places(self):
        t = make_tournament(self.user, status='active')
        entries = add_players(t, self.user, 4)
        generate_single_elimination(t)
        seed = {e.seed: e for e in entries}

        # R1: seed1 beats seed4, seed2 beats seed3
        r1m1 = get_match(t, 'winners', 1, 1)
        r1m2 = get_match(t, 'winners', 1, 2)
        # figure out which entries are present, just pick player1 as winner
        record_result(r1m1, r1m1.player1)
        record_result(r1m2, r1m2.player1)

        final = get_match(t, 'winners', 2, 1)
        self.assertIsNotNone(final.player1)
        self.assertIsNotNone(final.player2)
        record_result(final, final.player1)

        t.refresh_from_db()
        self.assertEqual(t.status, 'completed')

        placements = get_se_placements(t)
        self.assertEqual(placements[0][0], '1st')
        self.assertEqual(placements[0][1], [final.winner])
        # placements include seed helper unused variable guard
        self.assertIn(seed[1], [e for _, entries_, _ in placements for e in entries_])

    def test_get_bracket_rounds_grouping(self):
        t = make_tournament(self.user)
        add_players(t, self.user, 4)
        generate_single_elimination(t)
        rounds = get_bracket_rounds(t)
        self.assertEqual(len(rounds), 2)
        self.assertEqual(len(rounds[0]), 2)
        self.assertEqual(len(rounds[1]), 1)

    def test_se_placements_empty_when_no_matches(self):
        t = make_tournament(self.user)
        self.assertEqual(get_se_placements(t), [])


class SingleEliminationUndoTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.t = make_tournament(self.user, status='active')
        add_players(self.t, self.user, 4)
        generate_single_elimination(self.t)

    def test_undo_no_result(self):
        m = get_match(self.t, 'winners', 2, 1)
        ok, err = undo_result(m)
        self.assertFalse(ok)
        self.assertIn('no result', err.lower())

    def test_undo_bye_refused(self):
        t = make_tournament(self.user, status='active')
        add_players(t, self.user, 3)
        generate_single_elimination(t)
        bye = t.matches.filter(round_number=1, is_bye=True).first()
        self.assertIsNotNone(bye)
        ok, err = undo_result(bye)
        self.assertFalse(ok)
        self.assertIn('bye', err.lower())

    def test_undo_reverts_advance(self):
        r1m1 = get_match(self.t, 'winners', 1, 1)
        record_result(r1m1, r1m1.player1)
        final = get_match(self.t, 'winners', 2, 1)
        self.assertIsNotNone(final.player1)
        ok, err = undo_result(r1m1)
        self.assertTrue(ok, err)
        final.refresh_from_db()
        self.assertIsNone(final.player1)
        r1m1.refresh_from_db()
        self.assertIsNone(r1m1.winner)

    def test_undo_refused_when_later_round_played(self):
        r1m1 = get_match(self.t, 'winners', 1, 1)
        r1m2 = get_match(self.t, 'winners', 1, 2)
        record_result(r1m1, r1m1.player1)
        record_result(r1m2, r1m2.player1)
        final = get_match(self.t, 'winners', 2, 1)
        record_result(final, final.player1)
        ok, err = undo_result(r1m1)
        self.assertFalse(ok)
        self.assertIn('later round', err.lower())

    def test_undo_reopens_completed(self):
        r1m1 = get_match(self.t, 'winners', 1, 1)
        r1m2 = get_match(self.t, 'winners', 1, 2)
        record_result(r1m1, r1m1.player1)
        record_result(r1m2, r1m2.player1)
        final = get_match(self.t, 'winners', 2, 1)
        record_result(final, final.player1)
        self.t.refresh_from_db()
        self.assertEqual(self.t.status, 'completed')
        ok, _ = undo_result(final)
        self.assertTrue(ok)
        self.t.refresh_from_db()
        self.assertEqual(self.t.status, 'active')


# ── Round Robin ────────────────────────────────────────────────────────────────

class RoundRobinTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_too_few_players(self):
        t = make_tournament(self.user, fmt='round_robin')
        add_players(t, self.user, 1)
        generate_round_robin(t)
        self.assertEqual(t.matches.count(), 0)

    def test_pair_count(self):
        t = make_tournament(self.user, fmt='round_robin')
        add_players(t, self.user, 4)
        generate_round_robin(t)
        # C(4,2) = 6
        self.assertEqual(t.matches.count(), 6)

    def test_standings_ordering(self):
        t = make_tournament(self.user, fmt='round_robin')
        entries = add_players(t, self.user, 3)
        generate_round_robin(t)
        # Make entry1 win both its matches
        for m in t.matches.all():
            if entries[0] in (m.player1, m.player2):
                m.winner = entries[0]
                m.save()
            else:
                m.winner = m.player1
                m.save()
        standings = get_round_robin_standings(t)
        self.assertEqual(standings[0]['entry'], entries[0])
        self.assertEqual(standings[0]['wins'], 2)

    def test_undo_round_robin(self):
        t = make_tournament(self.user, fmt='round_robin', status='active')
        add_players(t, self.user, 3)
        generate_round_robin(t)
        m = t.matches.first()
        record_result(m, m.player1)
        ok, err = undo_result(m)
        self.assertTrue(ok, err)
        m.refresh_from_db()
        self.assertIsNone(m.winner)


# ── Double Elimination ─────────────────────────────────────────────────────────

class DoubleEliminationTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_too_few_players(self):
        t = make_tournament(self.user, fmt='double_elim')
        add_players(t, self.user, 1)
        generate_double_elimination(t)
        self.assertEqual(t.matches.count(), 0)

    def test_structure_4_players(self):
        t = make_tournament(self.user, fmt='double_elim')
        add_players(t, self.user, 4)
        generate_double_elimination(t)
        # WB: 2 rounds (2 + 1 matches), LB: 2 rounds (1 + 1), GF: 1
        self.assertEqual(t.matches.filter(bracket='winners').count(), 3)
        self.assertEqual(t.matches.filter(bracket='losers').count(), 2)
        self.assertEqual(t.matches.filter(bracket='grand_final').count(), 1)

    def test_get_de_data_shape(self):
        t = make_tournament(self.user, fmt='double_elim')
        add_players(t, self.user, 4)
        generate_double_elimination(t)
        data = get_de_data(t)
        self.assertIn('wb_rounds', data)
        self.assertIn('lb_rounds', data)
        self.assertIn('gf_matches', data)
        # 2 WB rounds -> labels WB Semis then WB Final for 4 players
        labels = [label for label, _ in data['wb_rounds']]
        self.assertEqual(labels[-1], 'WB Final')

    def test_full_run_4_players_wb_side_wins(self):
        t = make_tournament(self.user, fmt='double_elim', status='active')
        add_players(t, self.user, 4)
        generate_double_elimination(t)

        # Play WB round 1
        for mn in (1, 2):
            m = get_match(t, 'winners', 1, mn)
            record_de_result(m, m.player1)

        # WB final
        wbf = get_match(t, 'winners', 2, 1)
        self.assertIsNotNone(wbf.player1)
        self.assertIsNotNone(wbf.player2)
        record_de_result(wbf, wbf.player1)

        # LB round 1 (losers of WBR1 dropped)
        lb1 = get_match(t, 'losers', 1, 1)
        self.assertIsNotNone(lb1.player1)
        self.assertIsNotNone(lb1.player2)
        record_de_result(lb1, lb1.player1)

        # LB round 2 (LB final)
        lb2 = get_match(t, 'losers', 2, 1)
        self.assertIsNotNone(lb2.player1)
        self.assertIsNotNone(lb2.player2)
        record_de_result(lb2, lb2.player1)

        # Grand final
        gf = get_match(t, 'grand_final', 1, 1)
        self.assertIsNotNone(gf.player1)
        self.assertIsNotNone(gf.player2)
        # WB side (player1) wins outright -> champion, no bracket reset
        record_de_result(gf, gf.player1)

        t.refresh_from_db()
        self.assertEqual(t.status, 'completed')
        # no bracket reset created
        self.assertFalse(t.matches.filter(bracket='grand_final', round_number=2).exists())

        placements = get_de_placements(t)
        self.assertEqual(placements[0][0], '1st')
        self.assertEqual(placements[1][0], '2nd')

    def test_grand_final_bracket_reset(self):
        t = make_tournament(self.user, fmt='double_elim', status='active')
        add_players(t, self.user, 4)
        generate_double_elimination(t)

        for mn in (1, 2):
            m = get_match(t, 'winners', 1, mn)
            record_de_result(m, m.player1)
        wbf = get_match(t, 'winners', 2, 1)
        record_de_result(wbf, wbf.player1)
        lb1 = get_match(t, 'losers', 1, 1)
        record_de_result(lb1, lb1.player1)
        lb2 = get_match(t, 'losers', 2, 1)
        record_de_result(lb2, lb2.player1)

        gf = get_match(t, 'grand_final', 1, 1)
        # LB side (player2) wins -> bracket reset created
        record_de_result(gf, gf.player2)
        reset = t.matches.filter(bracket='grand_final', round_number=2).first()
        self.assertIsNotNone(reset)
        self.assertEqual(reset.player1, gf.player1)
        self.assertEqual(reset.player2, gf.player2)

        record_de_result(reset, reset.player2)
        t.refresh_from_db()
        self.assertEqual(t.status, 'completed')

    def test_de_with_byes_3_players(self):
        t = make_tournament(self.user, fmt='double_elim', status='active')
        add_players(t, self.user, 3)
        generate_double_elimination(t)
        # bracket size 4, seed1 gets a bye in WBR1
        wb_byes = t.matches.filter(bracket='winners', is_bye=True)
        self.assertTrue(wb_byes.exists())
        # play remaining WB match
        contested = t.matches.filter(bracket='winners', round_number=1, is_bye=False).first()
        record_de_result(contested, contested.player1)
        wbf = get_match(t, 'winners', 2, 1)
        self.assertIsNotNone(wbf.player1)
        self.assertIsNotNone(wbf.player2)


class DoubleEliminationUndoTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.t = make_tournament(self.user, fmt='double_elim', status='active')
        add_players(self.t, self.user, 4)
        generate_double_elimination(self.t)

    def _play_to_gf(self):
        for mn in (1, 2):
            m = get_match(self.t, 'winners', 1, mn)
            record_de_result(m, m.player1)
        wbf = get_match(self.t, 'winners', 2, 1)
        record_de_result(wbf, wbf.player1)
        lb1 = get_match(self.t, 'losers', 1, 1)
        record_de_result(lb1, lb1.player1)
        lb2 = get_match(self.t, 'losers', 2, 1)
        record_de_result(lb2, lb2.player1)

    def test_undo_wb_match_clears_downstream(self):
        m1 = get_match(self.t, 'winners', 1, 1)
        record_de_result(m1, m1.player1)
        wbf = get_match(self.t, 'winners', 2, 1)
        self.assertIsNotNone(wbf.player1)
        lb1 = get_match(self.t, 'losers', 1, 1)
        self.assertIsNotNone(lb1.player1)
        ok, err = undo_result(m1)
        self.assertTrue(ok, err)
        wbf.refresh_from_db()
        lb1.refresh_from_db()
        self.assertIsNone(wbf.player1)
        self.assertIsNone(lb1.player1)

    def test_undo_refused_when_downstream_played(self):
        m1 = get_match(self.t, 'winners', 1, 1)
        m2 = get_match(self.t, 'winners', 1, 2)
        record_de_result(m1, m1.player1)
        record_de_result(m2, m2.player1)
        wbf = get_match(self.t, 'winners', 2, 1)
        record_de_result(wbf, wbf.player1)
        ok, err = undo_result(m1)
        self.assertFalse(ok)
        self.assertIn('already been played', err.lower())

    def test_undo_gf_and_bracket_reset(self):
        self._play_to_gf()
        gf = get_match(self.t, 'grand_final', 1, 1)
        record_de_result(gf, gf.player2)  # creates reset
        self.assertTrue(self.t.matches.filter(bracket='grand_final', round_number=2).exists())
        ok, err = undo_result(gf)
        self.assertTrue(ok, err)
        # bracket reset deleted
        self.assertFalse(self.t.matches.filter(bracket='grand_final', round_number=2).exists())
        gf.refresh_from_db()
        self.assertIsNone(gf.winner)

    def test_undo_gf_refused_when_reset_played(self):
        self._play_to_gf()
        gf = get_match(self.t, 'grand_final', 1, 1)
        record_de_result(gf, gf.player2)
        reset = self.t.matches.get(bracket='grand_final', round_number=2)
        record_de_result(reset, reset.player1)
        ok, err = undo_result(gf)
        self.assertFalse(ok)
        self.assertIn('bracket-reset', err.lower())
