from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Event, Party, PartyMember, EventNotification, EventAttendance


def validate_roster(party, leader, members):
    """Проверить вместимость отряда и единственное назначение каждого игрока.

    Args:
        party: Отряд с доступным типом ивента.
        leader: Лидер либо None для свободного места лидера.
        members: Участники без отдельно указанного лидера.

    Raises:
        ValidationError: Есть дубли, превышена вместимость или игрок занят в другом отряде.
    """
    ids = [user.pk for user in members]
    if leader:
        ids.append(leader.pk)
    if len(ids) != len(set(ids)):
        raise ValidationError('Лидер не должен повторяться среди участников.')
    if len(ids) > party.event.event_type.party_size:
        raise ValidationError('В отряде недостаточно мест с учётом лидера.')
    others = Party.objects.filter(event_id=party.event_id).exclude(pk=party.pk)
    if (
        others.filter(leader_id__in=ids).exists()
        or PartyMember.objects.filter(party__in=others, user_id__in=ids).exists()
    ):
        raise ValidationError('Игрок уже назначен в другой отряд этого ивента.')


@transaction.atomic
def save_party_roster(party, leader, members):
    """Сохранить отряд под блокировкой общего постоянного состава.

    Args:
        party: Сохраняемый отряд.
        leader: Новый лидер либо None.
        members: Новый состав участников без лидера.

    Returns:
        Отряд с сохранённым лидером и актуальным составом.

    Raises:
        ValidationError: Состав не прошёл проверку вместимости или назначений.
        Event.DoesNotExist: Общий состав ивента удалён.
        Party.DoesNotExist: Редактируемый отряд удалён.
    """
    Event.objects.select_for_update().get(pk=party.event_id)
    party = (
        Party.objects.select_for_update(of=('self',))
        .select_related('event__event_type')
        .get(pk=party.pk)
    )
    members = list(members)
    validate_roster(party, leader, members)
    party.leader = leader
    party.save(update_fields=['leader'])
    selected = {user.pk for user in members}
    party.members.exclude(user_id__in=selected).delete()
    existing = set(party.members.values_list('user_id', flat=True))
    PartyMember.objects.bulk_create(
        [PartyMember(party=party, user=user) for user in members if user.pk not in existing]
    )
    return party


@transaction.atomic
def save_response(notification_id, user, status, comment, *, preserve_comment=False):
    """Сохранить ответ приглашённого под блокировкой даты проведения.

    Args:
        notification_id: ID приглашения на дату ивента.
        user: Получатель приглашения.
        status: Код ответа из EventAttendance.STATUS_CHOICES.
        comment: Комментарий длиной до 2000 символов.
        preserve_comment: Сохранить прежний комментарий вместо переданного.

    Returns:
        Созданный или обновлённый ответ игрока.

    Raises:
        EventNotification.DoesNotExist: Приглашение не найдено.
        ValidationError: Ответы закрыты, пользователь не приглашён или данные некорректны.
    """
    notification = EventNotification.objects.select_for_update().get(pk=notification_id)
    if not notification.response_open:
        raise ValidationError('Приём ответов завершён или приглашение ещё не отправлено.')
    if not notification.sent_to_users.filter(pk=user.pk).exists():
        raise ValidationError('Ответить могут только получатели приглашения.')
    if status not in dict(EventAttendance.STATUS_CHOICES):
        raise ValidationError('Выберите вариант ответа.')
    if preserve_comment:
        # Быстрый ответ меняет только статус: переносы строк комментария не проходят через скрытое поле.
        stored_comment = (
            EventAttendance.objects.filter(notification=notification, user=user)
            .values_list('comment', flat=True)
            .first()
        )
        comment = stored_comment or ''
    if len(comment) > 2000:
        raise ValidationError('Комментарий не должен превышать 2000 символов.')
    response, _ = EventAttendance.objects.update_or_create(
        notification=notification, user=user, defaults={'status': status, 'comment': comment}
    )
    return response
