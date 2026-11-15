from django.db.models import BigIntegerField, Case, Count, F, Q, When
from django.utils import timezone

from .crypto import MessageCryptoError
from .services import own_conversations


def dialogs_for(user):
    return (own_conversations(user).select_related('low_user__profile', 'high_user__profile', 'last_message')
        .annotate(my_read_id=Case(When(low_user=user, then=F('low_read_id')),
                                  default=F('high_read_id'), output_field=BigIntegerField()))
        .annotate(unread=Count('messages', filter=~Q(messages__sender=user) & Q(messages__pk__gt=F('my_read_id'))))
        .order_by('-updated_at', '-pk'))


def message_data(message, user, dialog=None):
    if dialog is not None:
        message.conversation = dialog
    available = True
    try:
        text = message.text_for(user)
    except MessageCryptoError:
        text, available = 'Сообщение недоступно', False
    dialog = message.conversation
    other_cursor = dialog.high_read_id if dialog.low_user_id == user.pk else dialog.low_read_id
    return {'id': message.pk, 'text': text, 'available': available, 'mine': message.sender_id == user.pk,
            'read': message.pk <= other_cursor, 'created_at': message.created_at.isoformat(),
            'time': timezone.localtime(message.created_at).strftime('%d.%m %H:%M')}


def dialog_rows(user, queryset):
    rows = []
    for dialog in queryset:
        last = message_data(dialog.last_message, user, dialog) if dialog.last_message else None
        rows.append({'dialog': dialog, 'other': dialog.other(user), 'unread': dialog.unread,
                     'preview': last['text'] if last else 'Сообщений пока нет', 'mine': last and last['mine']})
    return rows
