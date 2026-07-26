from datetime import datetime

from django.test import TestCase

from tournaments.forms import (
    AddExistingPlayerForm,
    PayoutForm,
    PlayerForm,
    RegisterForm,
    TournamentForm,
    VenueForm,
)
from tournaments.models import Player, Venue

from .helpers import make_tournament, make_user


class RegisterFormTests(TestCase):
    def test_valid(self):
        form = RegisterForm(data={
            'username': 'newuser',
            'email': 'x@example.com',
            'password1': 'sup3rSecret!',
            'password2': 'sup3rSecret!',
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_password_mismatch_invalid(self):
        form = RegisterForm(data={
            'username': 'newuser',
            'password1': 'sup3rSecret!',
            'password2': 'nope',
        })
        self.assertFalse(form.is_valid())


class VenueFormTests(TestCase):
    def test_valid(self):
        form = VenueForm(data={'name': 'Hall', 'city': 'Austin', 'state': 'TX'})
        self.assertTrue(form.is_valid(), form.errors)


class TournamentFormTests(TestCase):
    def test_minimal_valid(self):
        form = TournamentForm(data={'name': 'Cup', 'game_type': '8ball', 'format': 'single_elim'})
        self.assertTrue(form.is_valid(), form.errors)

    def test_clean_date_combines_to_noon(self):
        form = TournamentForm(data={
            'name': 'Cup', 'game_type': '8ball', 'format': 'single_elim', 'date': '2026-05-01',
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['date'], datetime(2026, 5, 1, 12, 0))

    def test_clean_date_empty(self):
        form = TournamentForm(data={'name': 'Cup', 'game_type': '8ball', 'format': 'single_elim'})
        self.assertTrue(form.is_valid())
        self.assertIsNone(form.cleaned_data['date'])

    def test_new_venue_requires_city_state(self):
        form = TournamentForm(data={
            'name': 'Cup', 'game_type': '8ball', 'format': 'single_elim',
            'venue_name': 'New Place',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('venue_city', form.errors)
        self.assertIn('venue_state', form.errors)

    def test_save_with_venue_creates_venue(self):
        user = make_user()
        form = TournamentForm(data={
            'name': 'Cup', 'game_type': '8ball', 'format': 'single_elim',
            'venue_name': 'Corner', 'venue_city': 'Austin', 'venue_state': 'TX',
            'venue_address': '1 St', 'venue_zip': '78701',
        })
        self.assertTrue(form.is_valid(), form.errors)
        tournament = form.save_with_venue(user)
        self.assertEqual(tournament.created_by, user)
        self.assertIsNotNone(tournament.venue)
        self.assertEqual(tournament.venue.name, 'Corner')
        self.assertEqual(Venue.objects.count(), 1)

    def test_save_with_existing_venue(self):
        user = make_user()
        venue = Venue.objects.create(name='Existing', city='Dallas', state='TX')
        form = TournamentForm(data={
            'name': 'Cup', 'game_type': '8ball', 'format': 'single_elim',
            'venue': venue.pk,
        })
        self.assertTrue(form.is_valid(), form.errors)
        tournament = form.save_with_venue(user)
        self.assertEqual(tournament.venue, venue)

    def test_save_with_no_venue(self):
        user = make_user()
        form = TournamentForm(data={'name': 'Cup', 'game_type': '8ball', 'format': 'single_elim'})
        self.assertTrue(form.is_valid(), form.errors)
        tournament = form.save_with_venue(user)
        self.assertIsNone(tournament.venue)

    def test_init_prepopulates_date_from_instance(self):
        user = make_user()
        t = make_tournament(user, date=datetime(2026, 3, 3, 12, 0))
        form = TournamentForm(instance=t)
        self.assertEqual(form.initial['date'], t.date.date())


class PlayerFormTests(TestCase):
    def test_valid(self):
        form = PlayerForm(data={'name': 'Efren', 'email': '', 'phone': ''})
        self.assertTrue(form.is_valid(), form.errors)

    def test_name_required(self):
        form = PlayerForm(data={'name': '', 'email': 'a@b.com'})
        self.assertFalse(form.is_valid())


class AddExistingPlayerFormTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.other = make_user(username='other')
        self.t = make_tournament(self.user)

    def test_queryset_excludes_entered_and_foreign_players(self):
        p_available = Player.objects.create(name='Available', created_by=self.user)
        p_entered = Player.objects.create(name='Entered', created_by=self.user)
        Player.objects.create(name='Foreign', created_by=self.other)
        from tournaments.models import TournamentEntry
        TournamentEntry.objects.create(tournament=self.t, player=p_entered, seed=1)

        form = AddExistingPlayerForm(user=self.user, tournament=self.t)
        qs = form.fields['player'].queryset
        self.assertIn(p_available, qs)
        self.assertNotIn(p_entered, qs)

    def test_no_user_gives_empty_queryset(self):
        form = AddExistingPlayerForm()
        self.assertEqual(form.fields['player'].queryset.count(), 0)


class PayoutFormTests(TestCase):
    def test_valid(self):
        form = PayoutForm(data={'place': 1, 'payout_type': 'flat', 'amount': '50.00'})
        self.assertTrue(form.is_valid(), form.errors)

    def test_invalid_missing_amount(self):
        form = PayoutForm(data={'place': 1, 'payout_type': 'flat'})
        self.assertFalse(form.is_valid())
