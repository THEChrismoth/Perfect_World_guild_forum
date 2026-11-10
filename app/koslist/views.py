from django.shortcuts import render

from profiles.models import class_icon_url
from .models import Guild, Player

def kos_view(request):
    guilds = Guild.objects.all()
    players = Player.objects.all()

    players_by_class = {}
    for player in players:
        if player.player_class not in players_by_class:
            players_by_class[player.player_class] = []
        players_by_class[player.player_class].append(player)

    context = {
            'players_by_class': players_by_class,
            'guilds': guilds,
            # Строка иконок всех классов над списком.
            'class_icons': [(label, class_icon_url(value)) for value, label in Player.CLASS_CHOICES],
           }
    
    return render(request, 'koslist/koslist.html', context)
