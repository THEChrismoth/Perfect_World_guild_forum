"""Права общения, отправка, блокировки и отметки прочтения."""

import uuid
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from core.roles import GUILD_GROUP, is_guild_member
from .crypto import encrypt
from .models import ContactBlock, Conversation, Message

MAX_LENGTH = 4000
PER_MINUTE = 20
PER_DAY = 200


def allowed_pair(sender, recipient):
    """Проверить активность аккаунтов и совместимость их ролей без учёта блокировок."""
    if (
        not sender.is_authenticated
        or not sender.is_active
        or not recipient.is_active
        or sender.pk == recipient.pk
    ):
        return False
    return (
        sender.is_staff
        or recipient.is_staff
        or (is_guild_member(sender) and is_guild_member(recipient))
    )


def blocked_pair(first, second):
    """Проверить наличие блокировки хотя бы в одном направлении."""
    return ContactBlock.objects.filter(
        Q(blocker=first, blocked=second) | Q(blocker=second, blocked=first)
    ).exists()


def can_contact(sender, recipient):
    """Проверить возможность новой отправки с учётом ролей и взаимных блокировок."""
    return allowed_pair(sender, recipient) and not blocked_pair(sender, recipient)


def contact_queryset(user):
    """Выбрать доступных собеседников, исключив себя и заблокированные пары."""
    users = User.objects.filter(is_active=True).exclude(pk=user.pk)
    if not user.is_staff:
        users = (
            users.filter(Q(is_staff=True) | Q(groups__name=GUILD_GROUP) | Q(is_superuser=True))
            if is_guild_member(user)
            else users.filter(is_staff=True)
        )
    blocked_ids = ContactBlock.objects.filter(blocker=user).values('blocked_id')
    blocked_by_ids = ContactBlock.objects.filter(blocked=user).values('blocker_id')
    return (
        users.exclude(pk__in=blocked_ids)
        .exclude(pk__in=blocked_by_ids)
        .distinct()
        .order_by('username')
    )


def own_conversations(user):
    """Выбрать диалоги пользователя без исключения для прав администратора."""
    return Conversation.objects.filter(Q(low_user=user) | Q(high_user=user))


def _lock_pair(first_id, second_id):
    """Заблокировать аккаунты в порядке ID и вернуть словарь найденных пользователей.

    Вызывать внутри транзакции. Единый порядок блокировок предотвращает взаимное
    ожидание при встречной отправке и изменении блокировок.
    """
    return {
        user.pk: user
        for user in User.objects.select_for_update()
        .filter(pk__in=[first_id, second_id])
        .order_by('pk')
    }


@transaction.atomic
@sensitive_variables()
def send_message(sender, recipient, text, client_id):
    """Сохранить зашифрованное сообщение с защитой от повторной отправки.

    Уведомление содержит только отправителя и ссылку на диалог. Повтор с тем же
    UUID и текстом возвращает существующее сообщение без повторного уведомления.

    Args:
        sender: Активный отправитель.
        recipient: Получатель сообщения.
        text: Непустой текст длиной до 4000 символов.
        client_id: UUID отправки, сохраняемый при повторе запроса.

    Returns:
        Пара из сообщения и признака создания новой записи.

    Raises:
        PermissionDenied: Аккаунт недоступен, роли несовместимы или есть блокировка.
        ValidationError: Текст, UUID или лимит отправки не прошли проверку.
        MessageCryptoError: Ключ недоступен или повторное сообщение не расшифровано.
    """
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_LENGTH:
        raise ValidationError('Введите сообщение от 1 до 4000 символов.')
    try:
        client_id = uuid.UUID(str(client_id))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('Обновите форму отправки сообщения.') from None
    users = _lock_pair(sender.pk, recipient.pk)
    sender, recipient = users.get(sender.pk), users.get(recipient.pk)
    if not sender or not recipient or not sender.is_active:
        raise PermissionDenied
    previous = (
        Message.objects.filter(sender=sender, client_id=client_id)
        .select_related('conversation')
        .first()
    )
    if previous:
        other_id = (
            previous.conversation.high_user_id
            if previous.conversation.low_user_id == sender.pk
            else previous.conversation.low_user_id
        )
        if other_id != recipient.pk or previous.text_for(sender) != text:
            raise ValidationError('Эта отправка уже использована. Обновите форму сообщения.')
        return previous, False
    if not allowed_pair(sender, recipient) or blocked_pair(sender, recipient):
        raise PermissionDenied('Отправка сообщений этому пользователю недоступна.')
    now = timezone.now()
    recent = Message.objects.filter(sender=sender)
    if (
        recent.filter(created_at__gte=now - timedelta(minutes=1)).count() >= PER_MINUTE
        or recent.filter(created_at__gte=now - timedelta(days=1)).count() >= PER_DAY
    ):
        raise ValidationError('Слишком много сообщений. Попробуйте отправить позже.')
    low, high = sorted([sender.pk, recipient.pk])
    dialog, _ = Conversation.objects.get_or_create(low_user_id=low, high_user_id=high)
    dialog = Conversation.objects.select_for_update().get(pk=dialog.pk)
    had_unread = (
        dialog.messages.filter(pk__gt=dialog.read_cursor(recipient))
        .exclude(sender=recipient)
        .exists()
    )
    token = encrypt(text, dialog.pk, sender.pk, client_id)
    message = Message.objects.create(
        conversation=dialog, sender=sender, client_id=client_id, ciphertext=token, created_at=now
    )
    dialog.last_message, dialog.updated_at = message, now
    dialog.save(update_fields=['last_message', 'updated_at'])
    if not had_unread:
        from notifications.utils import send_notification

        send_notification(
            recipient,
            'Новое личное сообщение',
            f'{sender.username} написал вам.',
            link=dialog.get_absolute_url(),
            notification_type='info',
        )
    return message, True


@transaction.atomic
def set_block(user, other, blocked):
    """Установить или снять собственную блокировку собеседника.

    Args:
        user: Пользователь, меняющий блокировку.
        other: Собеседник, к которому относится блокировка.
        blocked: Установить блокировку при True, снять при False.

    Raises:
        PermissionDenied: Пользователь неактивен, не вошёл или блокирует себя.
    """
    if not user.is_authenticated or not user.is_active or user.pk == other.pk:
        raise PermissionDenied
    _lock_pair(user.pk, other.pk)
    if blocked:
        ContactBlock.objects.get_or_create(blocker=user, blocked=other)
    else:
        ContactBlock.objects.filter(blocker=user, blocked=other).delete()


@transaction.atomic
def mark_read(dialog_id, user, up_to):
    """Продвинуть отметку прочтения до существующего сообщения своего диалога.

    Более ранняя отметка не уменьшает уже сохранённый курсор прочтения.

    Args:
        dialog_id: ID диалога пользователя.
        user: Участник, подтверждающий чтение.
        up_to: ID последнего прочитанного сообщения включительно.

    Returns:
        Диалог с актуальным курсором прочтения.

    Raises:
        Conversation.DoesNotExist: Диалог не найден среди собственных.
        ValidationError: Сообщение не принадлежит этому диалогу.
    """
    dialog = own_conversations(user).select_for_update().get(pk=dialog_id)
    if not dialog.messages.filter(pk=up_to).exists():
        raise ValidationError('Сообщение не найдено в этом диалоге.')
    field = 'low_read_id' if dialog.low_user_id == user.pk else 'high_read_id'
    if up_to > getattr(dialog, field):
        setattr(dialog, field, up_to)
        dialog.save(update_fields=[field])
    return dialog


def unread_count(user):
    """Посчитать входящие непрочитанные сообщения активного пользователя."""
    if not user.is_authenticated or not user.is_active:
        return 0
    return (
        Message.objects.filter(
            Q(conversation__low_user=user, pk__gt=F('conversation__low_read_id'))
            | Q(conversation__high_user=user, pk__gt=F('conversation__high_read_id'))
        )
        .exclude(sender=user)
        .count()
    )
