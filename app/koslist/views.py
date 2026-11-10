from django.shortcuts import render

from profiles.models import class_icon_url
from .models import Guild, Player

def kos_view(request):
    guilds = Guild.objects.all()

    players_by_class = {}
    for player in Player.objects.all():
        players_by_class.setdefault(player.player_class, []).append(player)

    # Группы классов в порядке списка классов, пустые не показываем.
    class_groups = [
        {'label': label, 'icon': class_icon_url(value), 'players': players_by_class[value]}
        for value, label in Player.CLASS_CHOICES
        if value in players_by_class
    ]

    context = {
        'guilds': guilds,
        'class_groups': class_groups,
        'players_count': sum(len(group['players']) for group in class_groups),
    }
    return render(request, 'koslist/koslist.html', context)
