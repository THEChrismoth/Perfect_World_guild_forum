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
    return application.status in DECISIONS.get(decision, ())


def send_to_voting(application, admin_user):
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
    application.status = 'approved'
    application.reviewed_by = admin_user
    application.save()
    if add_to_guild:
        group, _ = Group.objects.get_or_create(name=GUILD_GROUP)
        application.user.groups.add(group)
    send_notification(
        user=application.user,
        title='🎉 Заявка одобрена!',
        message='Поздравляем! Ваша заявка одобрена — добро пожаловать в гильдию!' if add_to_guild else
                'Поздравляем! Ваша заявка одобрена. Свяжитесь с администратором для вступления в гильдию.',
        notification_type='success',
        link=reverse('reception:my_applications'),
    )


def reject(application, admin_user, reason):
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
    """Голоса и комментарии одной лентой, новые сверху: голос — с комментарием или без, комментарий — отдельно."""
    items = [
        {'kind': vote.vote, 'label': vote.get_vote_display(), 'author': vote.voter,
         'text': vote.comment, 'created_at': vote.created_at}
        for vote in application.votes.select_related('voter')
    ] + [
        {'kind': 'comment', 'label': 'Комментарий', 'author': comment.author,
         'text': comment.text, 'created_at': comment.created_at}
        for comment in application.comments.select_related('author')
    ]
    return sorted(items, key=lambda item: item['created_at'], reverse=True)
