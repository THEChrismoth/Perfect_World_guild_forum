from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.utils import timezone
from django.views.decorators.http import require_POST
from core.roles import guild_member_required
from .models import EventType, Event, Party, PartyMember, EventNotification, EventAttendance
from .utils import get_attendance_stats, get_presence_report


@login_required
@guild_member_required
def event_index(request):
    """Страница со списком типов ивентов и отрядов."""
    
    # Получаем все активные типы ивентов.
    event_types = EventType.objects.filter(is_active=True)
    
    # Для каждого типа получаем отряды.
    event_types_data = []
    for event_type in event_types:
        try:
            event = Event.objects.get(event_type=event_type)
            parties = event.parties.all().prefetch_related('leader__profile', 'members__user__profile')
            
            # Формируем данные по отрядам.
            parties_data = []
            for party in parties:
                members_list = []
                
                # Лидер.
                if party.leader:
                    members_list.append({
                        'user': party.leader,
                        'role': 'leader',
                        'role_name': 'Лидер',
                        'profile': party.leader.profile
                    })
                
                # Участники.
                for member in party.members.all():
                    members_list.append({
                        'user': member.user,
                        'role': 'member',
                        'role_name': 'Участник',
                        'profile': member.user.profile
                    })
                
                parties_data.append({
                    'id': party.pk,
                'number': party.number,
                    'members': members_list,
                    'total_slots': event_type.party_size,
                    'filled_slots': len(members_list)
                })
            
            event_types_data.append({
                'event_type': event_type,
                'event': event,
                'parties': parties_data,
                'total_slots': event_type.total_slots
            })
            
        except Event.DoesNotExist:
            event_types_data.append({
                'event_type': event_type,
                'event': None,
                'parties': [],
                'total_slots': event_type.total_slots
            })
    
    context = {
        'event_types_data': event_types_data,
    }
    
    return render(request, 'events/event_index.html', context)


@login_required
@guild_member_required
def event_detail(request, event_type_slug):
    """Детальная страница конкретного типа ивента."""
    
    event_type = get_object_or_404(EventType, slug=event_type_slug, is_active=True)
    
    try:
        event = Event.objects.get(event_type=event_type)
        parties = event.parties.all().prefetch_related('leader__profile', 'members__user__profile')
        
        parties_data = []
        for party in parties:
            members_list = []
            
            if party.leader:
                members_list.append({
                    'user': party.leader,
                    'role': 'leader',
                    'role_name': 'Лидер',
                    'profile': party.leader.profile
                })
            
            for member in party.members.all():
                members_list.append({
                    'user': member.user,
                    'role': 'member',
                    'role_name': 'Участник',
                    'profile': member.user.profile
                })
            
            parties_data.append({
                'id': party.pk,
                'number': party.number,
                'members': members_list,
                'total_slots': event_type.party_size,
                'filled_slots': len(members_list)
            })
        
        event_data = event
        
    except Event.DoesNotExist:
        event_data = None
        parties_data = []
    
    context = {
        'event_type': event_type,
        'event': event_data,
        'parties': parties_data,
    }
    
    return render(request, 'events/event_detail.html', context)


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
        if not notification.response_open:
            messages.error(request, 'Приём ответов на этот ивент завершён или приглашение ещё не отправлено')
            return redirect('events:vote_results', notification_id=notification.pk)
        status = request.POST.get('status')
        comment = request.POST.get('comment', '')
        
        if status in ['yes', 'no', 'maybe']:
            if existing_vote:
                # Обновляем существующий голос.
                existing_vote.status = status
                existing_vote.comment = comment
                existing_vote.save()
                messages.success(request, f'Ваш ответ обновлен: {existing_vote.get_status_display()}')
            else:
                # Создаем новый голос.
                EventAttendance.objects.create(
                    notification=notification,
                    user=request.user,
                    status=status,
                    comment=comment
                )
                messages.success(request, 'Ваш ответ учтен! Спасибо за участие в опросе.')
            
            return redirect('events:vote_results', notification_id=notification_id)
        else:
            messages.error(request, 'Пожалуйста, выберите вариант ответа')
    
    # Статистика.
    stats = get_attendance_stats(notification_id)
    
    context = {
        'notification': notification,
        'event_type': event_type,
        'existing_vote': existing_vote,
        'stats': stats,
    }
    
    return render(request, 'events/vote_form.html', context)


@login_required
@guild_member_required
def vote_results(request, notification_id):
    """Страница результатов голосования."""
    
    notification = _get_invitation(request, notification_id)
    stats = get_attendance_stats(notification_id)
    
    if not notification:
        messages.error(request, 'Уведомление не найдено')
        return redirect('events:event_index')
    
    context = {
        'notification': notification,
        'event_type': notification.event_type,
        'stats': stats,
        'presence_rows': get_presence_report(notification),
    }
    
    return render(request, 'events/vote_results.html', context)


@login_required
@guild_member_required
def my_votes(request):
    """Страница с историей голосований пользователя."""
    
    votes = EventAttendance.objects.filter(
        user=request.user
    ).select_related('notification__event_type').order_by('-notification__event_date')
    
    context = {
        'votes': votes,
    }
    
    return render(request, 'events/my_votes.html', context)


@login_required
@guild_member_required
def party_edit(request, party_id):
    """Редактирует постоянный отряд по праву управления отрядами."""
    from django.core.exceptions import PermissionDenied, ValidationError
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
        notification = form.save()
        if request.POST.get('send') == 'yes':
            count = send_event_notification(notification.pk)
            messages.success(request, f'Приглашение отправлено: {count} получателей' if count else 'Дата сохранена, получателей нет')
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
