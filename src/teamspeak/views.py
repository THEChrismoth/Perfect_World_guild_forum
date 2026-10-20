from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from profiles.forms import TS3_UID_RE
from profiles.models import Profile
from reception.views import check_guild_member
from .models import TeamSpeakSettings, TsLink, TsRoom, TsTask
from .tasks import confirm_link, request_link

ROOM_NAME_MAX = 40

def card_context(request, profile_user):
    """Данные для блока TeamSpeak на странице профиля (показывается только владельцу)"""
    ts_settings = TeamSpeakSettings.load()
    link = TsLink.objects.filter(user=profile_user).first()
    last_verify = TsTask.objects.filter(user=profile_user, type='verify_link').first()
    rooms = list(TsRoom.objects.filter(owner=profile_user))
    active_rooms = [room for room in rooms if room.status in ('creating', 'active', 'deleting')]
    return {
        'ts_enabled': ts_settings.bot_last_seen is not None,
        'ts_bot_online': ts_settings.bot_online,
        'ts_address': ts_settings.display_address(request),
        'ts_is_guild_member': check_guild_member(profile_user),
        'ts_uid': (profile_user.profile.ts3_id or '').strip(),
        'ts_link': link,
        'ts_verify_error': last_verify.error if last_verify and last_verify.status == 'failed' and link and not link.verified else '',
        'ts_rooms': rooms,
        'ts_can_create_room': bool(link and link.verified) and len(active_rooms) < ts_settings.rooms_per_member,
        'ts_room_limit': ts_settings.rooms_per_member,
    }


def _back(request):
    return redirect('profile_view', username=request.user.username)


@login_required
@require_POST
def request_access(request):
    if not check_guild_member(request.user):
        messages.error(request, 'Доступ в TeamSpeak выдаётся только членам гильдии')
        return _back(request)
    ts_settings = TeamSpeakSettings.load()
    if not ts_settings.bot_online:
        messages.error(request, 'Бот TeamSpeak сейчас не на связи — попробуйте позже')
        return _back(request)

    # TS3 ID — из поля в блоке TeamSpeak или уже сохранённый в профиле
    uid = (request.POST.get('uid') or request.user.profile.ts3_id or '').strip()
    if not uid:
        messages.error(request, 'Укажите свой TS3 ID')
        return _back(request)
    if not TS3_UID_RE.match(uid):
        messages.error(request, 'Это не похоже на TS3 ID: нужен «Уникальный ID» локального идентификатора — '
                                '28 символов, в конце знак «=»')
        return _back(request)
    if TsLink.objects.filter(uid=uid, status='verified').exclude(user=request.user).exists():
        messages.error(request, 'Этот клиент TeamSpeak уже привязан к другому аккаунту сайта')
        return _back(request)

    request_link(request.user, uid,
                 lambda token: request.build_absolute_uri(reverse('teamspeak:confirm', args=[token])))
    messages.success(request, 'Бот отправил вам личное сообщение в TeamSpeak — откройте ссылку из него. '
                              'Вы должны быть подключены к серверу.')
    return _back(request)


@login_required
def confirm(request, token):
    link = TsLink.objects.filter(token=token).first()
    # Ссылка подтверждает, что TS-клиент принадлежит именно этому аккаунту сайта
    if not link or link.user_id != request.user.pk:
        raise Http404('Ссылка не найдена или принадлежит другому аккаунту')
    if link.verified:
        messages.info(request, 'TS3 ID уже подтверждён')
    else:
        confirm_link(link)
        # Подтверждённый ID сохраняем в профиль — вводить его вручную не нужно.
        # update() вместо save(): сигнал смены TS3 ID здесь не нужен
        Profile.objects.filter(user=request.user).update(ts3_id=link.uid)
        messages.success(request, 'TeamSpeak привязан! Бот выдаст вам группу «Член гильдии» в течение нескольких секунд.')
    return _back(request)


@login_required
@require_POST
def room_create(request):
    context = card_context(request, request.user)
    name = ' '.join((request.POST.get('name') or '').split())[:ROOM_NAME_MAX]
    if not context['ts_is_guild_member'] or not (context['ts_link'] and context['ts_link'].verified):
        messages.error(request, 'Создавать комнаты могут члены гильдии с подтверждённым TS3 ID')
    elif not context['ts_can_create_room']:
        messages.error(request, f'Можно создать не больше {context["ts_room_limit"]} комнат')
    elif not name:
        messages.error(request, 'Укажите название комнаты')
    else:
        room = TsRoom.objects.create(owner=request.user, name=name)
        TsTask.enqueue('create_room', user=request.user, room_id=room.pk, name=name, owner_uid=context['ts_link'].uid)
        messages.success(request, f'Комната «{name}» создаётся — она появится в TeamSpeak через несколько секунд')
    return _back(request)


@login_required
@require_POST
def room_delete(request, room_id):
    room = get_object_or_404(TsRoom, pk=room_id, owner=request.user)
    if room.status == 'failed' or not room.channel_id:
        room.delete()
    else:
        room.status = 'deleting'
        room.save(update_fields=['status'])
        TsTask.enqueue('delete_room', user=request.user, room_id=room.pk, cid=room.channel_id)
    messages.success(request, f'Комната «{room.name}» удаляется')
    return _back(request)
