"""Доступ модератора в админ-панель выдается вместе с группой «Модератор»."""
from django.contrib.auth.models import Group, User
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from .roles import MODERATOR_GROUP


def _sync_staff(user, is_moderator):
    # Суперпользователю доступ не трогаем: он администратор независимо от групп.
    if user.is_superuser or user.is_staff == is_moderator:
        return
    user.is_staff = is_moderator
    user.save(update_fields=['is_staff'])


@receiver(m2m_changed, sender=User.groups.through)
def moderator_group_changed(sender, instance, action, reverse, pk_set, **kwargs):
    if not reverse:
        # Изменили группы игрока. Реагируем, только если среди них «Модератор».
        if action == 'pre_clear':
            instance._was_moderator = instance.groups.filter(name=MODERATOR_GROUP).exists()
        elif action == 'post_clear' and getattr(instance, '_was_moderator', False):
            _sync_staff(instance, False)
        elif action in ('post_add', 'post_remove'):
            if Group.objects.filter(pk__in=pk_set, name=MODERATOR_GROUP).exists():
                _sync_staff(instance, action == 'post_add')
    elif instance.name == MODERATOR_GROUP:
        # Изменили состав самой группы «Модератор».
        if action == 'pre_clear':
            instance._cleared_users = list(instance.user_set.all())
        elif action == 'post_clear':
            for user in getattr(instance, '_cleared_users', []):
                _sync_staff(user, False)
        elif action in ('post_add', 'post_remove'):
            for user in User.objects.filter(pk__in=pk_set):
                _sync_staff(user, action == 'post_add')
