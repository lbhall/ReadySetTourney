import json

from django.test import TestCase
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
