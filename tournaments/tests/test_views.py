from decimal import Decimal

from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from tournaments.bracket import generate_single_elimination, record_result
from tournaments.models import ApiToken, Payout, Player, Tournament, TournamentEntry

from .helpers import add_players, make_tournament, make_user


class HomeViewTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_home_lists_tournaments(self):
        make_tournament(self.user, name='Alpha')
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Alpha')

    def test_home_status_filter(self):
        make_tournament(self.user, name='Pending One', status='pending')
        make_tournament(self.user, name='Active One', status='active')
        resp = self.client.get(reverse('home'), {'status': 'active'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Active One')
        self.assertNotContains(resp, 'Pending One')


class RegisterViewTests(TestCase):
    def test_get(self):
        resp = self.client.get(reverse('register'))
        self.assertEqual(resp.status_code, 200)

    def test_post_creates_and_logs_in(self):
        resp = self.client.post(reverse('register'), {
            'username': 'brandnew',
            'password1': 'sup3rSecret!',
            'password2': 'sup3rSecret!',
        })
        self.assertRedirects(resp, reverse('home'))
        self.assertTrue(self.client.session.get('_auth_user_id'))

    def test_authenticated_redirects(self):
        user = make_user()
        self.client.force_login(user)
        resp = self.client.get(reverse('register'))
        self.assertRedirects(resp, reverse('home'))

    def test_post_invalid_rerenders(self):
        resp = self.client.post(reverse('register'), {
            'username': 'x', 'password1': 'a', 'password2': 'b',
        })
        self.assertEqual(resp.status_code, 200)


class CreateTournamentViewTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_requires_login(self):
        resp = self.client.get(reverse('create_tournament'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login/', resp.url)

    def test_get_form(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('create_tournament'))
        self.assertEqual(resp.status_code, 200)

    def test_post_creates(self):
        self.client.force_login(self.user)
        resp = self.client.post(reverse('create_tournament'), {
            'name': 'My Cup', 'game_type': '8ball', 'format': 'single_elim',
        })
        t = Tournament.objects.get(name='My Cup')
        self.assertRedirects(resp, reverse('tournament_detail', args=[t.pk]))
        self.assertEqual(t.created_by, self.user)

    def test_post_invalid_rerenders(self):
        self.client.force_login(self.user)
        resp = self.client.post(reverse('create_tournament'), {'name': ''})
        self.assertEqual(resp.status_code, 200)


class DeleteTournamentViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.t = make_tournament(self.user)

    def test_delete_requires_owner(self):
        other = make_user(username='other')
        self.client.force_login(other)
        resp = self.client.post(reverse('delete_tournament', args=[self.t.pk]))
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(Tournament.objects.filter(pk=self.t.pk).exists())

    def test_delete_success(self):
        self.client.force_login(self.user)
        resp = self.client.post(reverse('delete_tournament', args=[self.t.pk]))
        self.assertRedirects(resp, reverse('home'))
        self.assertFalse(Tournament.objects.filter(pk=self.t.pk).exists())

    def test_delete_get_not_allowed(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('delete_tournament', args=[self.t.pk]))
        self.assertEqual(resp.status_code, 405)


class TournamentDetailViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.t = make_tournament(self.user)

    def test_detail_anonymous(self):
        resp = self.client.get(reverse('tournament_detail', args=[self.t.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context['can_manage'])

    def test_detail_owner_can_manage(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('tournament_detail', args=[self.t.pk]))
        self.assertTrue(resp.context['can_manage'])

    def test_detail_404(self):
        resp = self.client.get(reverse('tournament_detail', args=[9999]))
        self.assertEqual(resp.status_code, 404)


class AddNewPlayerViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.t = make_tournament(self.user)
        self.client.force_login(self.user)

    def test_add_new_player(self):
        resp = self.client.post(reverse('add_new_player', args=[self.t.pk]), {
            'name': 'Efren', 'email': '', 'phone': '',
        })
        self.assertRedirects(resp, reverse('tournament_detail', args=[self.t.pk]))
        self.assertEqual(self.t.entries.count(), 1)

    def test_add_duplicate_player_warns(self):
        self.client.post(reverse('add_new_player', args=[self.t.pk]), {'name': 'Efren'})
        self.client.post(reverse('add_new_player', args=[self.t.pk]), {'name': 'Efren'})
        self.assertEqual(self.t.entries.count(), 1)

    def test_add_invalid_form(self):
        resp = self.client.post(reverse('add_new_player', args=[self.t.pk]), {'name': ''})
        self.assertRedirects(resp, reverse('tournament_detail', args=[self.t.pk]))
        self.assertEqual(self.t.entries.count(), 0)

    def test_cannot_add_when_active(self):
        self.t.status = 'active'
        self.t.save()
        resp = self.client.post(reverse('add_new_player', args=[self.t.pk]), {'name': 'Efren'})
        self.assertRedirects(resp, reverse('tournament_detail', args=[self.t.pk]))
        self.assertEqual(self.t.entries.count(), 0)


class AddExistingPlayerViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.t = make_tournament(self.user)
        self.player = Player.objects.create(name='Existing', created_by=self.user)
        self.client.force_login(self.user)

    def test_add_existing(self):
        resp = self.client.post(reverse('add_existing_player', args=[self.t.pk]), {
            'player': self.player.pk,
        })
        self.assertRedirects(resp, reverse('tournament_detail', args=[self.t.pk]))
        self.assertEqual(self.t.entries.count(), 1)

    def test_add_existing_invalid(self):
        resp = self.client.post(reverse('add_existing_player', args=[self.t.pk]), {'player': 9999})
        self.assertRedirects(resp, reverse('tournament_detail', args=[self.t.pk]))
        self.assertEqual(self.t.entries.count(), 0)

    def test_cannot_add_when_active(self):
        self.t.status = 'active'
        self.t.save()
        resp = self.client.post(reverse('add_existing_player', args=[self.t.pk]), {
            'player': self.player.pk,
        })
        self.assertRedirects(resp, reverse('tournament_detail', args=[self.t.pk]))
        self.assertEqual(self.t.entries.count(), 0)


class RemovePlayerViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.t = make_tournament(self.user)
        self.entries = add_players(self.t, self.user, 3)
        self.client.force_login(self.user)

    def test_remove_reseeds(self):
        first = self.entries[0]
        resp = self.client.post(
            reverse('remove_player', args=[self.t.pk, first.pk])
        )
        self.assertRedirects(resp, reverse('tournament_detail', args=[self.t.pk]))
        self.assertEqual(self.t.entries.count(), 2)
        seeds = list(self.t.entries.order_by('seed').values_list('seed', flat=True))
        self.assertEqual(seeds, [1, 2])

    def test_cannot_remove_when_active(self):
        self.t.status = 'active'
        self.t.save()
        resp = self.client.post(
            reverse('remove_player', args=[self.t.pk, self.entries[0].pk])
        )
        self.assertRedirects(resp, reverse('tournament_detail', args=[self.t.pk]))
        self.assertEqual(self.t.entries.count(), 3)


class StartTournamentViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def test_too_few_players(self):
        t = make_tournament(self.user)
        add_players(t, self.user, 1)
        resp = self.client.post(reverse('start_tournament', args=[t.pk]))
        self.assertRedirects(resp, reverse('tournament_detail', args=[t.pk]))
        t.refresh_from_db()
        self.assertEqual(t.status, 'pending')

    def test_start_single_elim(self):
        t = make_tournament(self.user, fmt='single_elim')
        add_players(t, self.user, 4)
        resp = self.client.post(reverse('start_tournament', args=[t.pk]))
        self.assertRedirects(resp, reverse('bracket', args=[t.pk]))
        t.refresh_from_db()
        self.assertEqual(t.status, 'active')
        self.assertTrue(t.matches.exists())

    def test_start_double_elim(self):
        t = make_tournament(self.user, fmt='double_elim')
        add_players(t, self.user, 4)
        self.client.post(reverse('start_tournament', args=[t.pk]))
        t.refresh_from_db()
        self.assertEqual(t.status, 'active')
        self.assertTrue(t.matches.filter(bracket='grand_final').exists())

    def test_start_round_robin(self):
        t = make_tournament(self.user, fmt='round_robin')
        add_players(t, self.user, 3)
        self.client.post(reverse('start_tournament', args=[t.pk]))
        t.refresh_from_db()
        self.assertEqual(t.status, 'active')
        self.assertEqual(t.matches.count(), 3)

    def test_already_started(self):
        t = make_tournament(self.user, status='active')
        add_players(t, self.user, 4)
        resp = self.client.post(reverse('start_tournament', args=[t.pk]))
        self.assertRedirects(resp, reverse('tournament_detail', args=[t.pk]))


class BracketViewTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_pending_redirects(self):
        t = make_tournament(self.user)
        resp = self.client.get(reverse('bracket', args=[t.pk]))
        self.assertRedirects(resp, reverse('tournament_detail', args=[t.pk]))

    def test_single_elim_render(self):
        t = make_tournament(self.user, fmt='single_elim', status='active')
        add_players(t, self.user, 4)
        generate_single_elimination(t)
        resp = self.client.get(reverse('bracket', args=[t.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('bracket', resp.context)

    def test_double_elim_render(self):
        from tournaments.bracket import generate_double_elimination
        t = make_tournament(self.user, fmt='double_elim', status='active')
        add_players(t, self.user, 4)
        generate_double_elimination(t)
        resp = self.client.get(reverse('bracket', args=[t.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('wb_rounds', resp.context)

    def test_round_robin_render(self):
        from tournaments.bracket import generate_round_robin
        t = make_tournament(self.user, fmt='round_robin', status='active')
        add_players(t, self.user, 3)
        generate_round_robin(t)
        resp = self.client.get(reverse('bracket', args=[t.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('standings', resp.context)


class RecordAndUndoMatchViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.t = make_tournament(self.user, fmt='single_elim', status='active')
        add_players(self.t, self.user, 4)
        generate_single_elimination(self.t)
        self.client.force_login(self.user)

    def test_record_no_winner(self):
        m = self.t.matches.get(round_number=1, match_number=1)
        resp = self.client.post(reverse('record_match_result', args=[self.t.pk, m.pk]), {})
        self.assertRedirects(resp, reverse('bracket', args=[self.t.pk]))
        m.refresh_from_db()
        self.assertIsNone(m.winner)

    def test_record_invalid_winner(self):
        m = self.t.matches.get(round_number=1, match_number=1)
        # a valid entry but not in this match
        other = add_players(make_tournament(self.user, name='X'), self.user, 1)[0]
        resp = self.client.post(reverse('record_match_result', args=[self.t.pk, m.pk]), {
            'winner_id': other.pk,
        })
        self.assertRedirects(resp, reverse('bracket', args=[self.t.pk]))
        m.refresh_from_db()
        self.assertIsNone(m.winner)

    def test_record_valid(self):
        m = self.t.matches.get(round_number=1, match_number=1)
        resp = self.client.post(reverse('record_match_result', args=[self.t.pk, m.pk]), {
            'winner_id': m.player1.pk,
        })
        self.assertRedirects(resp, reverse('bracket', args=[self.t.pk]))
        m.refresh_from_db()
        self.assertEqual(m.winner, m.player1)

    def test_record_completes_tournament(self):
        m1 = self.t.matches.get(round_number=1, match_number=1)
        m2 = self.t.matches.get(round_number=1, match_number=2)
        record_result(m1, m1.player1)
        record_result(m2, m2.player1)
        final = self.t.matches.get(round_number=2, match_number=1)
        resp = self.client.post(reverse('record_match_result', args=[self.t.pk, final.pk]), {
            'winner_id': final.player1.pk,
        })
        self.assertRedirects(resp, reverse('bracket', args=[self.t.pk]))
        self.t.refresh_from_db()
        self.assertEqual(self.t.status, 'completed')

    def test_record_double_elim_path(self):
        from tournaments.bracket import generate_double_elimination
        t = make_tournament(self.user, fmt='double_elim', status='active')
        add_players(t, self.user, 4)
        generate_double_elimination(t)
        m = t.matches.get(bracket='winners', round_number=1, match_number=1)
        resp = self.client.post(reverse('record_match_result', args=[t.pk, m.pk]), {
            'winner_id': m.player1.pk,
        })
        self.assertRedirects(resp, reverse('bracket', args=[t.pk]))

    def test_undo_redirects_to_bracket_when_active(self):
        m = self.t.matches.get(round_number=1, match_number=1)
        record_result(m, m.player1)
        resp = self.client.post(reverse('undo_match_result', args=[self.t.pk, m.pk]))
        self.assertRedirects(resp, reverse('bracket', args=[self.t.pk]))

    def test_undo_failure_message(self):
        m = self.t.matches.get(round_number=2, match_number=1)  # no result
        resp = self.client.post(reverse('undo_match_result', args=[self.t.pk, m.pk]))
        self.assertEqual(resp.status_code, 302)


class MoneyAndPayoutViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.t = make_tournament(self.user)
        self.client.force_login(self.user)

    def test_edit_money_valid(self):
        resp = self.client.post(reverse('edit_tournament_money', args=[self.t.pk]), {
            'entry_fee': '20.00', 'added_money': '50',
        })
        self.assertRedirects(resp, reverse('tournament_detail', args=[self.t.pk]))
        self.t.refresh_from_db()
        self.assertEqual(self.t.entry_fee, Decimal('20.00'))
        self.assertEqual(self.t.added_money, Decimal('50'))

    def test_edit_money_blank_entry_fee(self):
        resp = self.client.post(reverse('edit_tournament_money', args=[self.t.pk]), {
            'entry_fee': '', 'added_money': '',
        })
        self.assertRedirects(resp, reverse('tournament_detail', args=[self.t.pk]))
        self.t.refresh_from_db()
        self.assertIsNone(self.t.entry_fee)
        self.assertEqual(self.t.added_money, Decimal('0'))

    def test_edit_money_invalid_number(self):
        resp = self.client.post(reverse('edit_tournament_money', args=[self.t.pk]), {
            'entry_fee': 'abc',
        })
        self.assertRedirects(resp, reverse('tournament_detail', args=[self.t.pk]))
        self.t.refresh_from_db()
        self.assertIsNone(self.t.entry_fee)

    def test_edit_money_negative(self):
        resp = self.client.post(reverse('edit_tournament_money', args=[self.t.pk]), {
            'entry_fee': '-5',
        })
        self.assertRedirects(resp, reverse('tournament_detail', args=[self.t.pk]))

    def test_edit_money_completed_blocked(self):
        self.t.status = 'completed'
        self.t.save()
        resp = self.client.post(reverse('edit_tournament_money', args=[self.t.pk]), {
            'entry_fee': '20',
        })
        self.assertRedirects(resp, reverse('tournament_detail', args=[self.t.pk]))
        self.t.refresh_from_db()
        self.assertIsNone(self.t.entry_fee)

    def test_add_payout(self):
        resp = self.client.post(reverse('add_payout', args=[self.t.pk]), {
            'place': 1, 'payout_type': 'flat', 'amount': '100',
        })
        self.assertRedirects(resp, reverse('tournament_detail', args=[self.t.pk]))
        self.assertEqual(self.t.payouts.count(), 1)

    def test_add_payout_invalid_form(self):
        resp = self.client.post(reverse('add_payout', args=[self.t.pk]), {'place': ''})
        self.assertRedirects(resp, reverse('tournament_detail', args=[self.t.pk]))
        self.assertEqual(self.t.payouts.count(), 0)

    def test_add_payout_completed_blocked(self):
        self.t.status = 'completed'
        self.t.save()
        resp = self.client.post(reverse('add_payout', args=[self.t.pk]), {
            'place': 1, 'payout_type': 'flat', 'amount': '100',
        })
        self.assertRedirects(resp, reverse('tournament_detail', args=[self.t.pk]))
        self.assertEqual(self.t.payouts.count(), 0)

    def test_remove_payout(self):
        p = Payout.objects.create(tournament=self.t, place=1, payout_type='flat', amount=Decimal('10'))
        resp = self.client.post(reverse('remove_payout', args=[self.t.pk, p.pk]))
        self.assertRedirects(resp, reverse('tournament_detail', args=[self.t.pk]))
        self.assertEqual(self.t.payouts.count(), 0)

    def test_remove_payout_completed_blocked(self):
        p = Payout.objects.create(tournament=self.t, place=1, payout_type='flat', amount=Decimal('10'))
        self.t.status = 'completed'
        self.t.save()
        resp = self.client.post(reverse('remove_payout', args=[self.t.pk, p.pk]))
        self.assertRedirects(resp, reverse('tournament_detail', args=[self.t.pk]))
        self.assertEqual(self.t.payouts.count(), 1)


class ApiTokenViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def test_get_no_token(self):
        resp = self.client.get(reverse('api_token'))
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context['token'])

    def test_post_generates(self):
        resp = self.client.post(reverse('api_token'))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context['reveal'])
        self.assertTrue(ApiToken.objects.filter(user=self.user).exists())

    def test_requires_login(self):
        self.client.logout()
        resp = self.client.get(reverse('api_token'))
        self.assertEqual(resp.status_code, 302)


class AddPayoutDuplicateViewTests(TransactionTestCase):
    """The view catches the IntegrityError on a duplicate place; that poisons a
    wrapping atomic (TestCase) transaction, so this path needs TransactionTestCase."""

    def test_add_payout_duplicate_place(self):
        user = make_user()
        t = make_tournament(user)
        Payout.objects.create(tournament=t, place=1, payout_type='flat', amount=Decimal('10'))
        self.client.force_login(user)
        resp = self.client.post(reverse('add_payout', args=[t.pk]), {
            'place': 1, 'payout_type': 'flat', 'amount': '100',
        })
        self.assertRedirects(resp, reverse('tournament_detail', args=[t.pk]))
        self.assertEqual(t.payouts.count(), 1)


class ReseedHelperViaRemove(TestCase):
    """Covers TournamentEntry re-seeding path more directly."""

    def test_seeds_are_sequential_after_removal(self):
        user = make_user()
        t = make_tournament(user)
        entries = add_players(t, user, 4)
        self.client.force_login(user)
        # remove the second seed
        self.client.post(reverse('remove_player', args=[t.pk, entries[1].pk]))
        remaining = list(TournamentEntry.objects.filter(tournament=t).order_by('seed'))
        self.assertEqual([e.seed for e in remaining], [1, 2, 3])
