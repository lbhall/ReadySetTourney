from django.contrib import admin
from .models import Venue, Tournament, Player, TournamentEntry, Match


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ['name', 'city', 'state']
    search_fields = ['name', 'city']


@admin.register(Tournament)
class TournamentAdmin(admin.ModelAdmin):
    list_display = ['name', 'game_type', 'format', 'status', 'player_count', 'created_by', 'created_at']
    list_filter = ['status', 'game_type', 'format']
    search_fields = ['name']
    readonly_fields = ['created_at']


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ['name', 'email', 'phone', 'created_by']
    search_fields = ['name', 'email']


@admin.register(TournamentEntry)
class TournamentEntryAdmin(admin.ModelAdmin):
    list_display = ['player', 'tournament', 'seed']
    list_filter = ['tournament']


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ['tournament', 'round_number', 'match_number', 'player1', 'player2', 'winner', 'is_bye']
    list_filter = ['tournament', 'round_number']
