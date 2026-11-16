import json
from datetime import datetime

from django.test import TestCase
from django.utils import timezone
from django.urls import reverse

from tournaments.models import ApiToken, Payout, Tournament, Venue

from .helpers import make_tournament, make_user


class ApiHelper(TestCase):
    def setUp(self):
        self.user = make_user()
        self.token = ApiToken.generate_for(self.user)

    def auth(self):
        return {'HTTP_AUTHORIZATION': f'Token {self.token.key}'}

    def post_json(self, url, payload, **extra):
        return self.client.post(
            url, data=json.dumps(payload), content_type='application/json', **extra
        )


class ObtainTokenTests(ApiHelper):
    def test_success_existing_token(self):
        resp = self.post_json(reverse('api_obtain_token'), {
            'username': 'owner', 'password': 'pass12345',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['token'], self.token.key)

    def test_creates_token_when_missing(self):
        user2 = make_user(username='fresh')
        resp = self.post_json(reverse('api_obtain_token'), {
            'username': 'fresh', 'password': 'pass12345',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(ApiToken.objects.filter(user=user2).exists())

    def test_invalid_credentials(self):
        resp = self.post_json(reverse('api_obtain_token'), {
            'username': 'owner', 'password': 'wrong',
        })
        self.assertEqual(resp.status_code, 401)

    def test_missing_fields(self):
        resp = self.post_json(reverse('api_obtain_token'), {'username': 'owner'})
        self.assertEqual(resp.status_code, 400)

    def test_bad_json(self):
        resp = self.client.post(
            reverse('api_obtain_token'), data='not json', content_type='application/json'
        )
        self.assertEqual(resp.status_code, 400)

    def test_non_dict_json(self):
        resp = self.post_json(reverse('api_obtain_token'), [1, 2, 3])
        self.assertEqual(resp.status_code, 400)


class CreateTournamentApiTests(ApiHelper):
    def test_missing_token(self):
        resp = self.post_json(reverse('api_create_tournament'), {'name': 'X'})
        self.assertEqual(resp.status_code, 401)

    def test_malformed_auth_header(self):
        resp = self.post_json(
            reverse('api_create_tournament'), {'name': 'X'},
            HTTP_AUTHORIZATION='Bearer abc',
        )
        self.assertEqual(resp.status_code, 401)

    def test_empty_token_value(self):
        resp = self.post_json(
            reverse('api_create_tournament'), {'name': 'X'},
            HTTP_AUTHORIZATION='Token ',
        )
        self.assertEqual(resp.status_code, 401)

    def test_unknown_token(self):
        resp = self.post_json(
            reverse('api_create_tournament'), {'name': 'X'},
            HTTP_AUTHORIZATION='Token deadbeef',
        )
        self.assertEqual(resp.status_code, 401)

    def test_bad_json(self):
        resp = self.client.post(
            reverse('api_create_tournament'), data='{bad', content_type='application/json',
            **self.auth(),
        )
        self.assertEqual(resp.status_code, 400)

    def test_non_dict_body(self):
        resp = self.post_json(reverse('api_create_tournament'), [1], **self.auth())
        self.assertEqual(resp.status_code, 400)

    def test_missing_name(self):
        resp = self.post_json(reverse('api_create_tournament'), {'name': '  '}, **self.auth())
        self.assertEqual(resp.status_code, 400)

    def test_invalid_game_type(self):
        resp = self.post_json(
            reverse('api_create_tournament'), {'name': 'X', 'game_type': 'foo'}, **self.auth()
        )
        self.assertEqual(resp.status_code, 400)

    def test_invalid_format(self):
        resp = self.post_json(
            reverse('api_create_tournament'), {'name': 'X', 'format': 'foo'}, **self.auth()
        )
        self.assertEqual(resp.status_code, 400)

    def test_invalid_date(self):
        resp = self.post_json(
            reverse('api_create_tournament'), {'name': 'X', 'date': '05/01/2026'}, **self.auth()
        )
        self.assertEqual(resp.status_code, 400)

    def test_invalid_entry_fee(self):
        resp = self.post_json(
            reverse('api_create_tournament'), {'name': 'X', 'entry_fee': 'abc'}, **self.auth()
        )
        self.assertEqual(resp.status_code, 400)

    def test_unknown_venue(self):
        resp = self.post_json(
            reverse('api_create_tournament'), {'name': 'X', 'venue_id': 9999}, **self.auth()
        )
        self.assertEqual(resp.status_code, 400)

    def test_teams_not_list(self):
        resp = self.post_json(
            reverse('api_create_tournament'), {'name': 'X', 'teams': 'nope'}, **self.auth()
        )
        self.assertEqual(resp.status_code, 400)

    def test_team_bad_type(self):
        resp = self.post_json(
            reverse('api_create_tournament'), {'name': 'X', 'teams': [123]}, **self.auth()
        )
        self.assertEqual(resp.status_code, 400)

    def test_team_no_name(self):
        resp = self.post_json(
            reverse('api_create_tournament'), {'name': 'X', 'teams': [{'name': ''}]}, **self.auth()
        )
        self.assertEqual(resp.status_code, 400)

    def test_duplicate_team(self):
        resp = self.post_json(
            reverse('api_create_tournament'),
            {'name': 'X', 'teams': ['A', 'a']}, **self.auth()
        )
        self.assertEqual(resp.status_code, 400)

    def test_full_create_with_string_and_dict_teams(self):
        venue = Venue.objects.create(name='Hall', city='Austin', state='TX')
        resp = self.post_json(
            reverse('api_create_tournament'),
            {
                'name': 'Big Open',
                'game_type': '9ball',
                'format': 'double_elim',
                'date': '2026-06-01',
                'entry_fee': '20',
                'added_money': '100',
                'venue_id': venue.pk,
                'notes': 'hello',
                'teams': ['Alice', {'name': 'Bob', 'email': 'b@x.com', 'phone': '555'}],
            },
            **self.auth(),
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['name'], 'Big Open')
        self.assertEqual(len(body['entries']), 2)
        self.assertIn('/tournaments/', body['url'])
        t = Tournament.objects.get(pk=body['id'])
        self.assertEqual(t.entries.count(), 2)
        # token last_used_at updated
        self.token.refresh_from_db()
        self.assertIsNotNone(self.token.last_used_at)


class AddPayoutApiTests(ApiHelper):
    def setUp(self):
        super().setUp()
        self.t = make_tournament(self.user)

    def test_missing_token(self):
        resp = self.post_json(
            reverse('api_add_payout', args=[self.t.pk]),
            {'place': 1, 'payout_type': 'flat', 'amount': '50'},
        )
        self.assertEqual(resp.status_code, 401)

    def test_tournament_not_found(self):
        resp = self.post_json(
            reverse('api_add_payout', args=[9999]),
            {'place': 1, 'payout_type': 'flat', 'amount': '50'}, **self.auth(),
        )
        self.assertEqual(resp.status_code, 404)

    def test_not_owner(self):
        other = make_user(username='other')
        other_t = make_tournament(other)
        resp = self.post_json(
            reverse('api_add_payout', args=[other_t.pk]),
            {'place': 1, 'payout_type': 'flat', 'amount': '50'}, **self.auth(),
        )
        self.assertEqual(resp.status_code, 404)

    def test_completed_blocked(self):
        self.t.status = 'completed'
        self.t.save()
        resp = self.post_json(
            reverse('api_add_payout', args=[self.t.pk]),
            {'place': 1, 'payout_type': 'flat', 'amount': '50'}, **self.auth(),
        )
        self.assertEqual(resp.status_code, 400)

    def test_bad_json(self):
        resp = self.client.post(
            reverse('api_add_payout', args=[self.t.pk]), data='{bad',
            content_type='application/json', **self.auth(),
        )
        self.assertEqual(resp.status_code, 400)

    def test_non_dict_body(self):
        resp = self.post_json(reverse('api_add_payout', args=[self.t.pk]), [1], **self.auth())
        self.assertEqual(resp.status_code, 400)

    def test_invalid_place(self):
        resp = self.post_json(
            reverse('api_add_payout', args=[self.t.pk]),
            {'place': 0, 'payout_type': 'flat', 'amount': '50'}, **self.auth(),
        )
        self.assertEqual(resp.status_code, 400)

    def test_invalid_payout_type(self):
        resp = self.post_json(
            reverse('api_add_payout', args=[self.t.pk]),
            {'place': 1, 'payout_type': 'weird', 'amount': '50'}, **self.auth(),
        )
        self.assertEqual(resp.status_code, 400)

    def test_invalid_amount_non_number(self):
        resp = self.post_json(
            reverse('api_add_payout', args=[self.t.pk]),
            {'place': 1, 'payout_type': 'flat', 'amount': 'abc'}, **self.auth(),
        )
        self.assertEqual(resp.status_code, 400)

    def test_negative_amount(self):
        resp = self.post_json(
            reverse('api_add_payout', args=[self.t.pk]),
            {'place': 1, 'payout_type': 'flat', 'amount': '-5'}, **self.auth(),
        )
        self.assertEqual(resp.status_code, 400)

    def test_duplicate_place_conflict(self):
        Payout.objects.create(tournament=self.t, place=1, payout_type='flat', amount=50)
        resp = self.post_json(
            reverse('api_add_payout', args=[self.t.pk]),
            {'place': 1, 'payout_type': 'flat', 'amount': '50'}, **self.auth(),
        )
        self.assertEqual(resp.status_code, 409)

    def test_success(self):
        resp = self.post_json(
            reverse('api_add_payout', args=[self.t.pk]),
            {'place': 1, 'payout_type': 'percentage', 'amount': '60'}, **self.auth(),
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['place'], 1)
        self.assertEqual(body['payout_type'], 'percentage')
        self.assertEqual(self.t.payouts.count(), 1)


class TournamentResultsTests(TestCase):
    """GET /api/tournaments/<id>/results/ is public and read-only."""

    def setUp(self):
        self.user = make_user()

    def _finish_double_elim(self, player_count=4):
        from tournaments.bracket import generate_double_elimination, record_de_result

        from .helpers import add_players, get_match

        t = make_tournament(
            self.user, name='Mid 2026 End of Season Tournament', fmt='double_elim',
            status='active', game_type='one_pocket', entry_fee='20', added_money='0',
        )
        add_players(t, self.user, player_count)
        Payout.objects.create(tournament=t, place=1, payout_type='percentage', amount='60')
        Payout.objects.create(tournament=t, place=2, payout_type='percentage', amount='40')
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
        record_de_result(gf, gf.player1)
        t.refresh_from_db()
        self.assertEqual(t.status, 'completed')
        return t

    def test_not_found(self):
        resp = self.client.get(reverse('api_tournament_results', args=[999]))
        self.assertEqual(resp.status_code, 404)
        self.assertIn('error', resp.json())

    def test_post_not_allowed(self):
        t = make_tournament(self.user)
        resp = self.client.post(reverse('api_tournament_results', args=[t.pk]))
        self.assertEqual(resp.status_code, 405)

    def test_pending_tournament_has_entries_but_no_results(self):
        from .helpers import add_players

        t = make_tournament(self.user, fmt='double_elim')
        add_players(t, self.user, 3)
        resp = self.client.get(reverse('api_tournament_results', args=[t.pk]))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['status'], 'pending')
        self.assertEqual([e['seed'] for e in data['entries']], [1, 2, 3])
        self.assertEqual(data['placements'], [])
        self.assertEqual(data['matches'], [])
        self.assertIsNone(data['date'])

    def test_completed_double_elim_reports_placements_and_payouts(self):
        t = self._finish_double_elim()
        t.date = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.get_current_timezone())
        t.save()
        resp = self.client.get(reverse('api_tournament_results', args=[t.pk]))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertEqual(data['id'], t.pk)
        self.assertEqual(data['name'], 'Mid 2026 End of Season Tournament')
        self.assertEqual(data['game_type'], 'one_pocket')
        self.assertEqual(data['format'], 'double_elim')
        self.assertEqual(data['status'], 'completed')
        self.assertEqual(data['date'], '2026-11-15')
        self.assertEqual(data['entry_fee'], '20.00')
        self.assertEqual(data['total_pot'], '80.00')
        self.assertTrue(data['url'].endswith(f'/tournaments/{t.pk}/bracket/'))

        self.assertEqual(len(data['entries']), 4)
        self.assertEqual(data['entries'][0]['name'], 'Player 1')

        placements = data['placements']
        self.assertEqual([p['label'] for p in placements], ['1st', '2nd', '3rd', '4th'])
        self.assertEqual([p['place'] for p in placements], [1, 2, 3, 4])
        self.assertEqual(placements[0]['payout'], '48.00')
        self.assertEqual(placements[1]['payout'], '32.00')
        self.assertIsNone(placements[2]['payout'])
        self.assertEqual(len(placements[0]['entries']), 1)
        self.assertEqual(placements[0]['entries'][0]['name'], 'Player 1')

        # Every played match names its winner; byes and unplayed matches do not.
        gf = next(m for m in data['matches'] if m['bracket'] == 'grand_final' and m['round'] == 1)
        self.assertEqual(gf['winner']['name'], 'Player 1')
        self.assertIn(gf['player2']['name'], {e['name'] for e in data['entries']})
        for m in data['matches']:
            self.assertEqual(set(m), {'bracket', 'round', 'match', 'player1', 'player2', 'winner', 'is_bye'})

    def test_single_elim_and_round_robin_placements(self):
        from tournaments.bracket import (
            generate_round_robin,
            generate_single_elimination,
            record_result,
        )

        from .helpers import add_players, get_match

        se = make_tournament(self.user, name='SE', fmt='single_elim', status='active')
        add_players(se, self.user, 2)
        generate_single_elimination(se)
        final = get_match(se, 'winners', 1, 1)
        record_result(final, final.player2)
        data = self.client.get(reverse('api_tournament_results', args=[se.pk])).json()
        self.assertEqual([p['label'] for p in data['placements']], ['1st', '2nd'])
        self.assertEqual(data['placements'][0]['entries'][0]['name'], 'Player 2')

        rr = make_tournament(self.user, name='RR', fmt='round_robin', status='active')
        add_players(rr, self.user, 3)
        Payout.objects.create(tournament=rr, place=1, payout_type='flat', amount='10')
        generate_round_robin(rr)
        for m in rr.matches.all():
            # Lowest seed wins every match it plays.
            winner = m.player1 if m.player1.seed < m.player2.seed else m.player2
            record_result(m, winner)
        data = self.client.get(reverse('api_tournament_results', args=[rr.pk])).json()
        self.assertEqual([p['label'] for p in data['placements']], ['1st', '2nd', '3rd'])
        self.assertEqual(data['placements'][0]['entries'][0]['name'], 'Player 1')
        self.assertEqual(data['placements'][0]['payout'], '10.00')
        self.assertIsNone(data['placements'][1]['payout'])
