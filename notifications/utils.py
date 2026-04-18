from .models import Notification
from django.contrib.auth.models import User, Group
from django.db import models


def send_notification(user, title, message, notification_type='info', link=None):
    """
    Отправить уведомление одному пользователю

    Параметры:
    - user: пользователь (объект User, username или id)
    - title: заголовок
    - message: текст
    - notification_type: тип уведомления
    - link: ссылка (опционально)
    """
    # Получаем пользователя если передан username или id
    if isinstance(user, str):
        try:
            user = User.objects.get(username=user)
        except User.DoesNotExist:
            return None
    elif isinstance(user, int):
        try:
            user = User.objects.get(id=user)
        except User.DoesNotExist:
            return None

    notification = Notification.objects.create(
        user=user,
        title=title,
        message=message,
        notification_type=notification_type,
        link=link
    )
    return notification


def send_notification_to_group(group_name, title, message, notification_type='info', link=None):
    """
    Отправить уведомление всем пользователям группы

    Параметры:
    - group_name: название группы
    - title: заголовок
    - message: текст
    - notification_type: тип уведомления
    - link: ссылка (опционально)
    """
    try:
        group = Group.objects.get(name=group_name)
        users = group.user_set.all()
        notifications = []
        for user in users:
            notifications.append(Notification(
                user=user,
                title=title,
                message=message,
                notification_type=notification_type,
                link=link
            ))
        Notification.objects.bulk_create(notifications)
        return len(notifications)
    except Group.DoesNotExist:
        return 0


def send_notification_to_all(title, message, notification_type='info', link=None):
    """Отправить уведомление всем пользователям"""
    users = User.objects.all()
    notifications = []
    for user in users:
        notifications.append(Notification(
            user=user,
            title=title,
            message=message,
            notification_type=notification_type,
            link=link
        ))
    Notification.objects.bulk_create(notifications)
    return len(notifications)


def send_notification_to_admins(title, message, notification_type='info', link=None):
    """Отправить уведомление всем администраторам"""
    admins = User.objects.filter(is_superuser=True)
    notifications = []
    for admin in admins:
        notifications.append(Notification(
            user=admin,
            title=title,
            message=message,
            notification_type=notification_type,
            link=link
        ))
    Notification.objects.bulk_create(notifications)
    return len(notifications)


def get_unread_count(user):
    """Получить количество непрочитанных уведомлений"""
    return Notification.objects.filter(user=user, is_read=False).count()


def mark_all_as_read(user):
    """Пометить все уведомления пользователя как прочитанные"""
    return Notification.objects.filter(user=user, is_read=False).update(is_read=True)