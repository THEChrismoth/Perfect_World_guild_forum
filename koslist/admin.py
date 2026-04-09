from django.contrib import admin
from .models import Guild, Player

@admin.register(Guild)
class GuildAdmin(admin.ModelAdmin):
    list_display = ['name', 'url_obs']
    list_per_page = 10

@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ['name', 'url_obs']
    list_per_page = 20
    list_filter = ['player_class']
    fieldsets = (
        ('Основная информация', {
            'fields': ('name', 'player_class', 'url_obs')
        }),
    )

