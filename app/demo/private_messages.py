"""Вымышленная переписка для изолированной демо-базы."""
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from messaging.crypto import configured, encrypt
from messaging.models import Conversation, Message


@transaction.atomic
def example_message(sender, recipient, text):
    """Создаёт вымышленный пример без настоящей рассылки уведомлений."""
    if not settings.DEMO_MODE or not configured():
        return
    low, high = sorted([sender.pk, recipient.pk])
    dialog, _ = Conversation.objects.get_or_create(low_user_id=low, high_user_id=high)
    key = uuid.uuid4()
    message = Message.objects.create(conversation=dialog, sender=sender, client_id=key,
                                     ciphertext=encrypt(text, dialog.pk, sender.pk, key))
    dialog.last_message = message
    dialog.updated_at = timezone.now()
    dialog.save(update_fields=['last_message', 'updated_at'])


def welcome(user):
    from django.contrib.auth.models import User

    leader = User.objects.filter(username='Северянка', is_staff=True).exclude(pk=user.pk).first()
    if leader:
        example_message(leader, user, 'Привет! Это пример личной переписки. Здесь можно обсудить '
                        'вступление в гильдию или договориться об ивенте. Попробуй отправить ответ.')
