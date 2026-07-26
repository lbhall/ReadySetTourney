from decimal import Decimal

from django.contrib.auth.models import User
from django.db import IntegrityError
from django.test import TestCase

from tournaments.models import (
    ApiToken,
    Match,
    Payout,
    Player,
    TournamentEntry,
    Venue,
)

from .helpers import add_players, make_tournament, make_user


class VenueModelTests(TestCase):
    def test_str(self):
        venue = Venue.objects.create(name='Corner Pocket', city='Austin', state='TX')
        self.assertEqual(str(venue), 'Corner Pocket — Austin, TX')

    def test_ordering(self):
        Venue.objects.create(name='Zebra', city='A', state='TX')
        Venue.objects.create(name='Alpha', city='B', state='TX')
        names = list(Venue.objects.values_list('name', flat=True))
        self.assertEqual(names, ['Alpha', 'Zebra'])


class TournamentModelTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_str(self):
        t = make_tournament(self.user, name='Summer Slam')
        self.assertEqual(str(t), 'Summer Slam')

    def test_player_count(self):
        t = make_tournament(self.user)
        self.assertEqual(t.player_count(), 0)
        add_players(t, self.user, 3)
        self.assertEqual(t.player_count(), 3)

    def test_display_names(self):
        t = make_tournament(self.user, game_type='9ball', fmt='double_elim')
        self.assertEqual(t.get_game_display_name(), '9-Ball')
        self.assertEqual(t.get_format_display_name(), 'Double Elimination')

    def test_display_names_unknown_fall_through(self):
        t = make_tournament(self.user)
        t.game_type = 'mystery'
        t.format = 'weird'
        self.assertEqual(t.get_game_display_name(), 'mystery')
        self.assertEqual(t.get_format_display_name(), 'weird')

    def test_total_pot_with_none_fees(self):
        t = make_tournament(self.user)
        t.entry_fee = None
        t.added_money = None
        add_players(t, self.user, 4)
        self.assertEqual(t.total_pot(), Decimal('0'))

    def test_total_pot_with_fees(self):
        t = make_tournament(self.user, entry_fee=Decimal('20'), added_money=Decimal('50'))
        add_players(t, self.user, 4)
        # 20 * 4 + 50
        self.assertEqual(t.total_pot(), Decimal('130'))

    def test_payout_amounts_percentage_and_flat(self):
        t = make_tournament(self.user, entry_fee=Decimal('10'), added_money=Decimal('0'))
        add_players(t, self.user, 10)  # pot = 100
        Payout.objects.create(tournament=t, place=1, payout_type='flat', amount=Decimal('40'))
        Payout.objects.create(tournament=t, place=2, payout_type='percentage', amount=Decimal('100'))
        amounts = t.payout_amounts()
        # flat 40 off top, percentage base = 60, 100% -> 60
        self.assertEqual(amounts[1], Decimal('40'))
        self.assertEqual(amounts[2], Decimal('60'))

    def test_payout_amounts_flat_exceeds_pot_base_clamped(self):
        t = make_tournament(self.user, entry_fee=Decimal('0'), added_money=Decimal('0'))
        Payout.objects.create(tournament=t, place=1, payout_type='flat', amount=Decimal('50'))
        Payout.objects.create(tournament=t, place=2, payout_type='percentage', amount=Decimal('50'))
        amounts = t.payout_amounts()
        self.assertEqual(amounts[1], Decimal('50'))
        # percentage base clamped to 0
        self.assertEqual(amounts[2], Decimal('0'))


class PlayerModelTests(TestCase):
    def test_str(self):
        user = make_user()
        p = Player.objects.create(name='Efren', created_by=user)
        self.assertEqual(str(p), 'Efren')


class TournamentEntryModelTests(TestCase):
    def test_str_and_unique_together(self):
        user = make_user()
        t = make_tournament(user)
        p = Player.objects.create(name='Shane', created_by=user)
        entry = TournamentEntry.objects.create(tournament=t, player=p, seed=3)
        self.assertEqual(str(entry), 'Shane (#3) — Test Open')
        with self.assertRaises(IntegrityError):
            TournamentEntry.objects.create(tournament=t, player=p, seed=4)


class MatchModelTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.t = make_tournament(self.user)
        self.entries = add_players(self.t, self.user, 2)

    def test_str(self):
        m = Match.objects.create(tournament=self.t, round_number=2, match_number=5)
        self.assertEqual(str(m), 'R2M5 — Test Open')

    def test_is_complete_and_is_ready(self):
        m = Match.objects.create(
            tournament=self.t, round_number=1, match_number=1,
            player1=self.entries[0], player2=self.entries[1],
        )
        self.assertFalse(m.is_complete())
        self.assertTrue(m.is_ready())
        m.winner = self.entries[0]
        m.save()
        self.assertTrue(m.is_complete())
        self.assertFalse(m.is_ready())

    def test_unique_together(self):
        Match.objects.create(tournament=self.t, bracket='winners', round_number=1, match_number=1)
        with self.assertRaises(IntegrityError):
            Match.objects.create(tournament=self.t, bracket='winners', round_number=1, match_number=1)


class PayoutModelTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.t = make_tournament(self.user)

    def test_str_suffixes(self):
        p1 = Payout.objects.create(tournament=self.t, place=1, payout_type='flat', amount=Decimal('1'))
        p2 = Payout.objects.create(tournament=self.t, place=2, payout_type='flat', amount=Decimal('1'))
        p3 = Payout.objects.create(tournament=self.t, place=3, payout_type='flat', amount=Decimal('1'))
        p4 = Payout.objects.create(tournament=self.t, place=4, payout_type='flat', amount=Decimal('1'))
        self.assertEqual(str(p1), '1st place — Test Open')
        self.assertEqual(str(p2), '2nd place — Test Open')
        self.assertEqual(str(p3), '3rd place — Test Open')
        self.assertEqual(str(p4), '4th place — Test Open')

    def test_calculated_amount(self):
        flat = Payout.objects.create(tournament=self.t, place=1, payout_type='flat', amount=Decimal('30'))
        pct = Payout.objects.create(tournament=self.t, place=2, payout_type='percentage', amount=Decimal('25'))
        self.assertEqual(flat.calculated_amount(Decimal('100')), Decimal('30'))
        self.assertEqual(pct.calculated_amount(Decimal('200')), Decimal('50'))

    def test_unique_together_place(self):
        Payout.objects.create(tournament=self.t, place=1, payout_type='flat', amount=Decimal('1'))
        with self.assertRaises(IntegrityError):
            Payout.objects.create(tournament=self.t, place=1, payout_type='flat', amount=Decimal('2'))


class ApiTokenModelTests(TestCase):
    def test_str_and_generate_for_rotates(self):
        user = User.objects.create_user(username='api', password='pass12345')
        token = ApiToken.generate_for(user)
        self.assertEqual(str(token), 'API token for api')
        first_key = token.key
        self.assertEqual(len(first_key), 64)
        rotated = ApiToken.generate_for(user)
        self.assertNotEqual(rotated.key, first_key)
        # still a single token (OneToOne)
        self.assertEqual(ApiToken.objects.filter(user=user).count(), 1)
