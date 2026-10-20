"""Постановка задач боту и обработка их результатов на стороне сайта"""
from django.urls import reverse
from django.utils import timezone

from .models import TeamSpeakSettings, TsLink, TsRoom, TsTask


def apply_task_result(task):
    """Последствия выполненной (или проваленной) задачи для данных сайта"""
    from notifications.utils import send_notification

    payload = task.payload or {}

    if task.type == 'create_room':
        room = TsRoom.objects.filter(pk=payload.get('room_id')).first()
        if room:
            if task.status == 'done':
                room.status = 'active'
                room.channel_id = (task.result or {}).get('cid')
                room.error = ''
            else:
                room.status = 'failed'
                room.error = task.error
            room.save()

    elif task.type == 'delete_room':
        room = TsRoom.objects.filter(pk=payload.get('room_id')).first()
        if room:
            if task.status == 'done':
                room.delete()
            else:
                room.status = 'active'
                room.error = task.error
                room.save()

    elif task.type == 'install_license' and task.status == 'done':
        TeamSpeakSettings.objects.filter(pk=1).update(license_installed_at=timezone.now())

    elif task.type == 'grant_guild' and task.status == 'done' and task.user:
        send_notification(task.user, '🎧 Доступ в TeamSpeak',
                          'Вам выдана группа «Член гильдии» в TeamSpeak — комнаты гильдии открыты.',
                          notification_type='success')

    if task.status == 'failed' and task.user and task.type in ('verify_link', 'grant_guild', 'create_room', 'delete_room'):
        send_notification(task.user, '⚠️ TeamSpeak', f'{task.get_type_display()}: {task.error}',
                          notification_type='error', link=reverse('profile_view', args=[task.user.username]))


def request_link(user, uid, confirm_url_builder):
    """Начать привязку: бот отправит игроку в TeamSpeak ссылку подтверждения"""
    link, _ = TsLink.objects.update_or_create(
        user=user, defaults={'uid': uid, 'status': 'pending', 'token': TsLink.new_token(), 'verified_at': None}
    )
    TsTask.enqueue('verify_link', user=user, uid=uid, username=user.username,
                   url=confirm_url_builder(link.token))
    return link


def confirm_link(link):
    link.status = 'verified'
    link.verified_at = timezone.now()
    link.save(update_fields=['status', 'verified_at'])
    TsTask.enqueue('grant_guild', user=link.user, uid=link.uid)


def revoke_link(link):
    """Снять группу гильдии с привязанного клиента и удалить привязку"""
    if link.verified:
        TsTask.enqueue('revoke_guild', user=link.user, uid=link.uid)
    link.delete()
