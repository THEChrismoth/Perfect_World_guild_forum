from django.contrib.auth.models import User, Group
from django.utils import timezone
from notifications.utils import send_notification
from .models import EventNotification


def get_recipient_users(notification):
    """
    Получить список пользователей-получателей на основе выбранных групп
    
    Параметры:
    - notification: объект EventNotification
    """
    groups = notification.recipient_groups.all()
    
    if groups.exists():
        # Если выбраны группы - берем пользователей из этих групп
        users = User.objects.filter(groups__in=groups, is_active=True).distinct()
    else:
        # Если группы не выбраны - берем всех членов группы "Член гильдии"
        try:
            guild_group = Group.objects.get(name='Член гильдии')
            users = guild_group.user_set.filter(is_active=True)
        except Group.DoesNotExist:
            # Если группы "Член гильдии" нет, берем всех активных пользователей
            users = User.objects.filter(is_active=True)
    
    return users


def send_event_notification(notification_id):
    """
    Отправить уведомление выбранным группам пользователей через модуль notifications
    
    Параметры:
    - notification_id: ID уведомления
    """
    
    try:
        notification = EventNotification.objects.get(id=notification_id)
    except EventNotification.DoesNotExist:
        return 0
    
    event_type = notification.event_type
    event_date = notification.event_date
    event_date_str = event_date.strftime('%d.%m.%Y')
    weekday = get_weekday_name(event_date)
    
    # Получаем пользователей для отправки
    users = get_recipient_users(notification)
    
    # Ссылка для голосования
    vote_url = f"/events/vote/{notification.id}/"
    
    # Формируем сообщение БЕЗ текстовой ссылки (только кнопка добавится в notifications/utils.py)
    full_message = f"""{notification.message}

📅 Дата: {weekday}, {event_date_str}
🎯 Ивент: {event_type.icon} {event_type.name}"""
    
    # Отправляем уведомления через модуль notifications
    sent_count = 0
    for user in users:
        send_notification(
            user=user,
            title=notification.subject,
            message=full_message,
            notification_type='warning',
            link=vote_url  # Кнопка создается здесь
        )
        notification.sent_to_users.add(user)
        sent_count += 1
    
    # Обновляем время отправки
    notification.sent_at = timezone.now()
    notification.save()
    
    return sent_count


def get_attendance_stats(notification_id):
    """
    Получить статистику ответов на уведомление
    
    Параметры:
    - notification_id: ID уведомления
    """
    
    try:
        notification = EventNotification.objects.get(id=notification_id)
    except EventNotification.DoesNotExist:
        return {
            'yes_count': 0,
            'no_count': 0,
            'maybe_count': 0,
            'total_count': 0,
            'yes_users': [],
            'no_users': [],
            'maybe_users': [],
            'notification': None
        }
    
    attendances = notification.attendances.select_related('user__profile')
    
    yes_users = [a for a in attendances if a.status == 'yes']
    no_users = [a for a in attendances if a.status == 'no']
    maybe_users = [a for a in attendances if a.status == 'maybe']
    
    return {
        'yes_count': len(yes_users),
        'no_count': len(no_users),
        'maybe_count': len(maybe_users),
        'total_count': attendances.count(),
        'yes_users': yes_users,
        'no_users': no_users,
        'maybe_users': maybe_users,
        'notification': notification
    }


def get_weekday_name(date_obj):
    """Получить русское название дня недели"""
    weekdays = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
    return weekdays[date_obj.weekday()]
