"""Решения по заявке: допустить до голосования, одобрить, отклонить. Кандидат получает уведомление о каждом."""

from django.contrib.auth.models import Group
from django.urls import reverse
from django.utils import timezone

from core.roles import GUILD_GROUP
from notifications.utils import send_notification

# Какое решение из какого статуса можно принять.
DECISIONS = {
    'voting': ('pending',),
    'approve': ('voting',),
    'reject': ('pending', 'voting'),
}


def can_decide(application, decision):
    """Проверить допустимость решения для текущего статуса заявки."""
    return application.status in DECISIONS.get(decision, ())


def send_to_voting(application, admin_user):
    """Допустить заявку до голосования и уведомить кандидата.

    Args:
        application: Заявка, для которой вызывающий код проверил допустимость решения.
        admin_user: Пользователь, принявший решение.
    """
    application.status = 'voting'
    application.approved_at = timezone.now()
    application.reviewed_by = admin_user
    application.save()
    send_notification(
        user=application.user,
        title='📝 Заявка допущена до голосования',
        message='Ваша заявка прошла предварительную проверку и допущена до голосования членов гильдии.',
        notification_type='application',
        link=reverse('reception:application_detail', args=[application.id]),
    )


def approve(application, admin_user, add_to_guild=False):
    """Одобрить заявку и при необходимости включить кандидата в гильдию.

    Args:
        application: Заявка после проверки прав и допустимости перехода вызывающим кодом.
        admin_user: Пользователь, принявший решение.
        add_to_guild: Добавить кандидата в группу гильдии при True.
    """
    application.status = 'approved'
    application.reviewed_by = admin_user
    application.save()
    if add_to_guild:
        group, _ = Group.objects.get_or_create(name=GUILD_GROUP)
        application.user.groups.add(group)
    send_notification(
        user=application.user,
        title='🎉 Заявка одобрена!',
        message='Поздравляем! Ваша заявка одобрена — добро пожаловать в гильдию!'
        if add_to_guild
        else 'Поздравляем! Ваша заявка одобрена. Свяжитесь с администратором для вступления в гильдию.',
        notification_type='success',
        link=reverse('reception:my_applications'),
    )


def reject(application, admin_user, reason):
    """Отклонить заявку, сохранить причину и уведомить кандидата.

    Args:
        application: Заявка после проверки допустимости решения вызывающим кодом.
        admin_user: Пользователь, принявший решение.
        reason: Причина отказа, показываемая кандидату.
    """
    application.status = 'rejected'
    application.admin_comment = reason
    application.reviewed_by = admin_user
    application.save()
    send_notification(
        user=application.user,
        title='❌ Заявка отклонена',
        message=f'Ваша заявка была отклонена. Причина: {reason}',
        notification_type='error',
        link=reverse('reception:my_applications'),
    )


def discussion_items(application):
    """Объединить голоса и комментарии заявки в ленту от новых к старым.

    Args:
        application: Заявка с голосами и отдельными комментариями.

    Returns:
        Список словарей с видом записи, подписью, автором, текстом и временем.
    """
    items = [
        {
            'kind': vote.vote,
            'label': vote.get_vote_display(),
            'author': vote.voter,
            'text': vote.comment,
            'created_at': vote.created_at,
        }
        for vote in application.votes.select_related('voter')
    ] + [
        {
            'kind': 'comment',
            'label': 'Комментарий',
            'author': comment.author,
            'text': comment.text,
            'created_at': comment.created_at,
        }
        for comment in application.comments.select_related('author')
    ]
    return sorted(items, key=lambda item: item['created_at'], reverse=True)
