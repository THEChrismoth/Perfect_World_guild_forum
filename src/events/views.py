from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import EventType, Event, Party, PartyMember, EventNotification, EventAttendance
from .utils import get_attendance_stats


@login_required
def event_index(request):
    """Страница со списком типов ивентов и отрядов"""
    
    # Получаем все активные типы ивентов
    event_types = EventType.objects.filter(is_active=True)
    
    # Для каждого типа получаем отряды
    event_types_data = []
    for event_type in event_types:
        try:
            event = Event.objects.get(event_type=event_type)
            parties = event.parties.all().prefetch_related('leader__profile', 'members__user__profile')
            
            # Формируем данные по отрядам
            parties_data = []
            for party in parties:
                members_list = []
                
                # Лидер
                if party.leader:
                    members_list.append({
                        'user': party.leader,
                        'role': 'leader',
                        'role_name': 'Лидер',
                        'profile': party.leader.profile
                    })
                
                # Участники
                for member in party.members.all():
                    members_list.append({
                        'user': member.user,
                        'role': 'member',
                        'role_name': 'Участник',
                        'profile': member.user.profile
                    })
                
                parties_data.append({
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
def event_detail(request, event_type_slug):
    """Детальная страница конкретного типа ивента"""
    
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
def vote_view(request, notification_id):
    """Страница голосования по уведомлению"""
    
    notification = get_object_or_404(EventNotification, id=notification_id)
    event_type = notification.event_type
    
    # Проверяем, голосовал ли уже пользователь
    existing_vote = EventAttendance.objects.filter(
        notification=notification,
        user=request.user
    ).first()
    
    if request.method == 'POST':
        status = request.POST.get('status')
        comment = request.POST.get('comment', '')
        
        if status in ['yes', 'no', 'maybe']:
            if existing_vote:
                # Обновляем существующий голос
                existing_vote.status = status
                existing_vote.comment = comment
                existing_vote.save()
                messages.success(request, f'Ваш ответ обновлен: {existing_vote.get_status_display()}')
            else:
                # Создаем новый голос
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
    
    # Статистика
    stats = get_attendance_stats(notification_id)
    
    context = {
        'notification': notification,
        'event_type': event_type,
        'existing_vote': existing_vote,
        'stats': stats,
    }
    
    return render(request, 'events/vote_form.html', context)


@login_required
def vote_results(request, notification_id):
    """Страница результатов голосования"""
    
    stats = get_attendance_stats(notification_id)
    notification = stats['notification']
    
    if not notification:
        messages.error(request, 'Уведомление не найдено')
        return redirect('events:event_index')
    
    context = {
        'notification': notification,
        'event_type': notification.event_type,
        'stats': stats,
    }
    
    return render(request, 'events/vote_results.html', context)


@login_required
def my_votes(request):
    """Страница с историей голосований пользователя"""
    
    votes = EventAttendance.objects.filter(
        user=request.user
    ).select_related('notification__event_type').order_by('-notification__event_date')
    
    context = {
        'votes': votes,
    }
    
    return render(request, 'events/my_votes.html', context)
