"""Синхронизация группы гильдии и привязки TS3 ID с TeamSpeak."""

from django.contrib.auth.models import User
from django.db.models.signals import m2m_changed, pre_save
from django.dispatch import receiver

from profiles.models import Profile
from .models import GUILD_GROUP, TsLink, TsTask
from .tasks import revoke_link


@receiver(m2m_changed, sender=User.groups.through)
def guild_group_changed(sender, instance, action, pk_set, reverse, **kwargs):
    """Поставить задачи выдачи или снятия TS-группы при изменении членства на сайте.

    Работает только для подтверждённых привязок: клиент в TS должен быть точно этим игроком.
    """
    if reverse or action not in ('post_add', 'post_remove', 'post_clear'):
        return
    link = TsLink.objects.filter(user=instance, status='verified').first()
    if not link:
        return
    is_member = instance.groups.filter(name=GUILD_GROUP).exists()
    if action == 'post_add' and is_member:
        TsTask.enqueue('grant_guild', user=instance, uid=link.uid)
    elif action in ('post_remove', 'post_clear') and not is_member:
        TsTask.enqueue('revoke_guild', user=instance, uid=link.uid)


@receiver(pre_save, sender=Profile)
def ts3_id_changed(sender, instance, **kwargs):
    """Отозвать старую привязку при изменении TS3 ID профиля."""
    if not instance.pk:
        return
    old = Profile.objects.filter(pk=instance.pk).values_list('ts3_id', flat=True).first()
    if (old or '').strip() == (instance.ts3_id or '').strip():
        return
    link = TsLink.objects.filter(user_id=instance.user_id).first()
    # Тот же ID, что и в привязке (например, его записал сам сайт после подтверждения) — ничего не меняем.
    if link and link.uid != (instance.ts3_id or '').strip():
        revoke_link(link)
