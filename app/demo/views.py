from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_not_required, login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .accounts import DEMO_ROLES
from .guests import create_guest, find_guest, read_guests, remember_guest
from .limits import make_room, take_ip_slot


def _require_demo_member(request):
    from core.roles import is_guild_member
    if not settings.DEMO_MODE:
        raise Http404
    if not is_guild_member(request.user):
        raise PermissionDenied('Раздел доступен членам гильдии')


@login_required
def teamspeak_preview(request):
    """Показывает возможности TS без подключения к голосовому серверу."""
    _require_demo_member(request)
    from skirmishes.models import Skirmish
    return render(request, 'demo/teamspeak.html', {
        'demo_linked': bool(request.session.get('demo_ts_linked')),
        'demo_room': request.session.get('demo_ts_room', ''),
        'active_skirmish': Skirmish.objects.filter(ended_at__isnull=True).first(),
    })


@login_required
@require_POST
def teamspeak_action(request):
    """Имитирует привязку и комнату только в сессии посетителя, без задач настоящему боту."""
    _require_demo_member(request)
    action = request.POST.get('action')
    if action == 'link':
        request.session['demo_ts_linked'] = True
        messages.success(request, 'Демонстрация: TS3 ID подтверждён, группа гильдии выдана.')
    elif action == 'create_room':
        name = ' '.join(request.POST.get('name', '').split())
        if not request.session.get('demo_ts_linked'):
            messages.error(request, 'Сначала покажите привязку аккаунта.')
        elif not name or len(name) > 40:
            messages.error(request, 'Укажите название комнаты до 40 символов.')
        elif request.session.get('demo_ts_room'):
            messages.error(request, 'В демонстрации доступна одна личная комната.')
        else:
            request.session['demo_ts_room'] = name
            messages.success(request, 'Демонстрация: комната создана, вам выданы права администратора комнаты.')
    elif action == 'delete_room':
        request.session.pop('demo_ts_room', None)
        messages.success(request, 'Демонстрационная комната удалена.')
    else:
        messages.error(request, 'Неизвестное действие.')
    return redirect('demo:teamspeak')


@login_required
@require_POST
def skirmish_presence(request):
    """Добавляет демонстрационную отметку TS только самому посетителю активного сбора."""
    _require_demo_member(request)
    from skirmishes.models import Participant, Skirmish
    if not request.session.get('demo_ts_linked'):
        messages.info(request, 'Сначала покажите привязку TeamSpeak в демо.')
        return redirect('demo:teamspeak')
    with transaction.atomic():
        session = Skirmish.objects.select_for_update().filter(ended_at__isnull=True).first()
        if session:
            now = timezone.now()
            entry, _ = Participant.objects.get_or_create(skirmish=session, user=request.user)
            entry.minutes = max(entry.minutes, session.min_minutes)
            entry.first_seen_at = entry.first_seen_at or now
            entry.last_seen_at = now
            entry.last_minute = now.replace(second=0, microsecond=0)
            entry.save()
            session.last_report_at = now
            session.save(update_fields=['last_report_at'])
    if not session:
        messages.info(request, 'Нет активного замеса. Войдите ролью администратора и начните сбор.')
        return redirect('skirmishes:index')
    messages.success(request, f'Демонстрация: добавлены отметки TS до порога {session.min_minutes} мин. Настоящий бот не подключён.')
    return redirect(session)


@login_not_required
@require_POST
def demo_login(request, role):
    """Вход в демо-роль без пароля: в личный аккаунт этого браузера или в новый. Только при DEMO_MODE."""
    if not settings.DEMO_MODE or role not in DEMO_ROLES:
        raise Http404
    user = find_guest(role, read_guests(request).get(role))
    if user is None:
        if not take_ip_slot(request):
            messages.error(request, 'С вашего адреса создано слишком много демо-аккаунтов. Попробуйте через час.')
            return redirect('/')
        if not make_room():
            messages.error(request, 'Демо сейчас переполнено посетителями. Попробуйте через полчаса.')
            return redirect('/')
        user = create_guest(role)
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    messages.success(request, f'Вы вошли как {DEMO_ROLES[role]["title"].lower()} {user.username}.')
    response = redirect('/')
    remember_guest(request, response, role, user)
    return response
