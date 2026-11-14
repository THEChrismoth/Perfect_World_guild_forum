from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.views.decorators.http import require_POST
from core.roles import guild_member_required
from .models import EventType, Event, Party, EventNotification, EventAttendance
from .utils import get_attendance_stats, get_presence_report


def _visible_invitations(user):
    """Возвращает даты, доступные игроку или управляющему ивентами."""
    dates = EventNotification.objects.select_related('event_type')
    if any(user.has_perm(f'events.{action}_eventnotification') for action in ('view', 'change', 'add')):
        return dates
    return dates.filter(sent_at__isnull=False, sent_to_users=user)


def _party_cards(event):
    """Готовит постоянные отряды из предварительно загруженных данных."""
    if not event:
        return []
    result = []
    for party in event.parties.all():
        members = []
        if party.leader:
            members.append({'user': party.leader, 'profile': party.leader.profile, 'role_name': 'Лидер', 'role': 'leader'})
        members.extend({'user': member.user, 'profile': member.user.profile, 'role_name': 'Участник', 'role': 'member'}
                       for member in party.members.all())
        result.append({'id': party.pk, 'number': party.number, 'members': members,
                       'total_slots': event.event_type.party_size, 'filled_slots': len(members)})
    return result


def _roster_queryset():
    """Загружает состав и профили без запроса на каждого игрока."""
    from django.db.models import Prefetch
    return Event.objects.select_related('event_type').prefetch_related(Prefetch(
        'parties', queryset=Party.objects.select_related('leader__profile').prefetch_related('members__user__profile')))


@login_required
@guild_member_required
def event_index(request):
    """Показывает типы ивентов, постоянные составы и ближайшие даты."""
    from django.db.models import Prefetch
    types = EventType.objects.filter(is_active=True).prefetch_related(Prefetch('roster', queryset=_roster_queryset()))
    cards = []
    for kind in types:
        event = getattr(kind, 'roster', None)
        parties = _party_cards(event)
        cards.append({'event_type': kind, 'event': event, 'parties': parties,
                      'filled_slots': sum(party['filled_slots'] for party in parties), 'total_slots': kind.total_slots})
    upcoming = _visible_invitations(request.user).filter(event_date__gte=timezone.localdate(), event_type__is_active=True).order_by('event_date', 'start_time')[:6]
    return render(request, 'events/event_index.html', {'event_types_data': cards, 'upcoming': upcoming})


@login_required
@guild_member_required
def event_detail(request, event_type_slug):
    """Показывает постоянные отряды и историю дат одного типа ивента."""
    event_type = get_object_or_404(EventType, slug=event_type_slug, is_active=True)
    event = _roster_queryset().filter(event_type=event_type).first()
    parties = _party_cards(event)
    from django.core.paginator import Paginator
    dates = _visible_invitations(request.user).filter(event_type=event_type).order_by('-event_date', '-pk')
    page = Paginator(dates, 10).get_page(request.GET.get('page'))
    return render(request, 'events/event_detail.html', {
        'event_type': event_type, 'event': event, 'parties': parties, 'dates_page': page,
        'filled_slots': sum(party['filled_slots'] for party in parties),
    })


@login_required
@guild_member_required
def vote_view(request, notification_id):
    """Страница голосования по уведомлению."""
    
    notification = _get_invitation(request, notification_id)
    event_type = notification.event_type
    
    # Проверяем, голосовал ли уже пользователь.
    existing_vote = EventAttendance.objects.filter(
        notification=notification,
        user=request.user
    ).first()
    
    if request.method == 'POST':
        return_home = request.POST.get('return_to') == 'home'
        if not notification.response_open:
            messages.error(request, 'Приём ответов на этот ивент завершён или приглашение ещё не отправлено')
            if return_home:
                return redirect('home')
            return redirect('events:vote_results', notification_id=notification.pk)
        from .services import save_response
        try:
            save_response(notification.pk, request.user, request.POST.get('status'),
                          request.POST.get('comment', ''), preserve_comment=return_home)
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
            if return_home:
                return redirect('home')
        else:
            messages.success(request, 'Ваш ответ сохранён')
            if return_home:
                return redirect('home')
            return redirect('events:vote_results', notification_id=notification_id)

    # Статистика.
    stats = get_attendance_stats(notification_id)
    
    context = {
        'notification': notification,
        'event_type': event_type,
        'existing_vote': existing_vote,
        'can_answer': notification.response_open and notification.sent_to_users.filter(pk=request.user.pk).exists(),
        'stats': stats,
    }
    
    return render(request, 'events/vote_form.html', context)


@login_required
@guild_member_required
def vote_results(request, notification_id):
    """Страница результатов голосования."""
    
    notification = _get_invitation(request, notification_id)
    stats = get_attendance_stats(notification_id)
    
    from django.core.paginator import Paginator
    rows = get_presence_report(notification)
    page = Paginator(rows, 40).get_page(request.GET.get('page'))
    context = {
        'notification': notification, 'event_type': notification.event_type, 'stats': stats,
        'presence_rows': page, 'presence_page': page, 'invited_count': notification.sent_to_users.count(),
        'present_count': sum(row['present'] for row in rows),
        'unanswered_count': sum(row['answer'] is None for row in rows),
        'can_answer': notification.response_open and notification.sent_to_users.filter(pk=request.user.pk).exists(),
    }
    
    return render(request, 'events/vote_results.html', context)


@login_required
@guild_member_required
def my_votes(request):
    """Страница с историей голосований пользователя."""
    
    votes = EventAttendance.objects.filter(user=request.user, notification__sent_at__isnull=False).select_related('notification__event_type').order_by('-notification__event_date')
    from django.core.paginator import Paginator
    votes = Paginator(votes, 20).get_page(request.GET.get('page'))
    
    context = {
        'votes': votes,
    }
    
    return render(request, 'events/my_votes.html', context)


@login_required
@guild_member_required
def party_edit(request, party_id):
    """Редактирует постоянный отряд по праву управления отрядами."""
    from .forms import PartyRosterForm
    from .services import save_party_roster

    if not request.user.has_perm('events.change_party'):
        raise PermissionDenied
    party = get_object_or_404(Party.objects.select_related('event__event_type'), pk=party_id)
    form = PartyRosterForm(request.POST or None, party=party)
    if request.method == 'POST' and form.is_valid():
        try:
            save_party_roster(party, form.cleaned_data['leader'], form.cleaned_data['members'])
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, 'Постоянный отряд сохранён')
            return redirect(party.event.get_absolute_url())
    return render(request, 'events/party_edit.html', {'form': form, 'party': party, 'event_type': party.event.event_type})


def _get_invitation(request, notification_id):
    """Открывает приглашение получателю или пользователю с правом просмотра."""
    notification = get_object_or_404(EventNotification.objects.select_related('event_type'), pk=notification_id)
    manager = any(request.user.has_perm(f'events.{action}_eventnotification') for action in ('view', 'change', 'add'))
    if not manager and (not notification.sent_at or not notification.sent_to_users.filter(pk=request.user.pk).exists()):
        raise Http404
    return notification


@login_required
@guild_member_required
def invitation_create(request, event_type_slug):
    """Назначает дату и отправляет приглашение вручную."""
    from .forms import InvitationForm
    from .utils import send_event_notification
    if not request.user.has_perm('events.add_eventnotification'):
        raise PermissionDenied
    event_type = get_object_or_404(EventType, slug=event_type_slug, is_active=True)
    form = InvitationForm(request.POST or None, event_type=event_type)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                notification = form.save()
                count = send_event_notification(notification.pk) if request.POST.get('send') == 'yes' else 0
        except IntegrityError:
            form.add_error('event_date', 'На эту дату уже назначен ивент этого типа.')
        else:
            if request.POST.get('send') == 'yes':
                messages.success(request, f'Приглашение отправлено: {count} получателей' if count else 'Дата сохранена, получателей нет или ивент уже завершён')
            else:
                messages.success(request, 'Дата сохранена. Приглашение можно отправить позже')
            return redirect('events:vote_results', notification_id=notification.pk)
    return render(request, 'events/invitation_form.html', {'form': form, 'event_type': event_type})


@login_required
@guild_member_required
@require_POST
def invitation_send(request, notification_id):
    """Отправляет сохранённое приглашение по явному действию пользователя."""
    from .utils import send_event_notification
    if not request.user.has_perm('events.change_eventnotification'):
        raise PermissionDenied
    notification = get_object_or_404(EventNotification, pk=notification_id)
    if notification.event_date < timezone.localdate():
        messages.error(request, 'Нельзя отправить приглашение на прошедшую дату')
    else:
        count = send_event_notification(notification.pk)
        messages.success(request, f'Приглашение отправлено: {count}' if count else 'Приглашение уже отправлено или нет получателей')
    return redirect('events:vote_results', notification_id=notification.pk)
