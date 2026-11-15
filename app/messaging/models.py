import uuid

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import models
from django.urls import reverse
from django.utils import timezone


class Conversation(models.Model):
    low_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='dialogs_low')
    high_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='dialogs_high')
    low_read_id = models.PositiveBigIntegerField(default=0)
    high_read_id = models.PositiveBigIntegerField(default=0)
    last_message = models.ForeignKey('Message', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    updated_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['low_user', 'high_user'], name='unique_direct_conversation'),
            models.CheckConstraint(condition=models.Q(low_user__lt=models.F('high_user')), name='ordered_dialog_users'),
        ]
        ordering = ['-updated_at', '-pk']

    def __str__(self):
        return f'Диалог #{self.pk}'

    def get_absolute_url(self):
        return reverse('messaging:conversation', args=[self.pk])

    def has_user(self, user):
        return user.is_authenticated and user.pk in (self.low_user_id, self.high_user_id)

    def other(self, user):
        if not self.has_user(user):
            raise PermissionDenied
        return self.high_user if user.pk == self.low_user_id else self.low_user

    def read_cursor(self, user):
        if not self.has_user(user):
            raise PermissionDenied
        return self.low_read_id if user.pk == self.low_user_id else self.high_read_id


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='direct_messages_sent')
    client_id = models.UUIDField(default=uuid.uuid4)
    ciphertext = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['pk']
        constraints = [models.UniqueConstraint(fields=['sender', 'client_id'], name='unique_message_retry')]
        indexes = [models.Index(fields=['conversation', 'id']), models.Index(fields=['sender', 'created_at'])]

    def __str__(self):
        return f'Личное сообщение #{self.pk}'

    def text_for(self, user):
        if not self.conversation.has_user(user):
            raise PermissionDenied
        from .crypto import decrypt
        return decrypt(self.ciphertext, self.conversation_id, self.sender_id, self.client_id)


class ContactBlock(models.Model):
    blocker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='contacts_blocked')
    blocked = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='contacts_blocked_by')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['blocker', 'blocked'], name='unique_contact_block'),
            models.CheckConstraint(condition=~models.Q(blocker=models.F('blocked')), name='no_self_contact_block'),
        ]
