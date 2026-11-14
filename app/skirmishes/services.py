"""Общие правила быстрых сборов для сайта и учёта TeamSpeak."""
import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import SiteSettings
from core.roles import is_guild_member
from .models import AttendanceCorrection, CodeAttempt, Participant, Skirmish


def can_manage(user):
    return user.is_active and is_guild_member(user) and user.has_perm('skirmishes.manage_skirmish')


def require_manager(user):
    if not can_manage(user):
        raise PermissionDenied('У вас нет права управлять замесами')


def start_skirmish(actor, title=''):
    """Возвращает текущий сбор или создаёт единственный активный замес."""
    require_manager(actor)
    title = title.strip()
    if len(title) > 120:
        raise ValidationError('Название должно быть не длиннее 120 символов.')
    SiteSettings.load()
    try:
        with transaction.atomic():
            config = SiteSettings.objects.select_for_update().get(pk=1)
            current = Skirmish.objects.filter(ended_at__isnull=True).first()
            if current:
                return current, False
            channel = config.skirmish_ts_channel.strip()
            if not channel:
                raise ValidationError('Сначала задайте TS-канал для замесов в настройках сайта.')
            now = timezone.now()
            previous_code = Skirmish.objects.values_list('code', flat=True).first()
            code = f'{secrets.randbelow(10000):04d}'
            while code == previous_code:
                code = f'{secrets.randbelow(10000):04d}'
            session = Skirmish.objects.create(
                title=title or f'Замес {timezone.localtime(now):%d.%m, %H:%M}', code=code,
                organizer=actor, started_at=now, ts_channel=channel,
                include_children=config.skirmish_include_children, min_minutes=config.skirmish_min_minutes,
            )
            return session, True
    except IntegrityError:
        current = Skirmish.objects.filter(ended_at__isnull=True).first()
        if current:
            return current, False
        raise


def join_by_code(user, code):
    """Отмечает вход по коду с ограничением перебора на аккаунт во всех процессах сайта."""
    if not user.is_active or not is_guild_member(user):
        raise PermissionDenied('Сборы доступны только членам гильдии')
    error = None
    participant = None
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        now = timezone.now()
        attempt, _ = CodeAttempt.objects.get_or_create(user=user, defaults={'window_started_at': now})
        if now - attempt.window_started_at >= timedelta(minutes=1):
            attempt.window_started_at, attempt.count = now, 0
        if attempt.count >= 10:
            error = 'Слишком много попыток. Повторите через минуту.'
        else:
            attempt.count += 1
            attempt.save()
            session = (Skirmish.objects.select_for_update()
                       .filter(ended_at__isnull=True, code=code).first())
            if not session or len(code) != 4 or not code.isascii() or not code.isdigit():
                error = 'Активный замес с таким кодом не найден.'
            else:
                participant, _ = Participant.objects.get_or_create(skirmish=session, user=user)
                if participant.joined_at is None:
                    participant.joined_at = now
                    participant.save(update_fields=['joined_at'])
    if error:
        raise ValidationError(error)
    return participant


def finish_skirmish(session_id, actor):
    require_manager(actor)
    with transaction.atomic():
        session = Skirmish.objects.select_for_update().get(pk=session_id)
        if session.active:
            session.ended_at = timezone.now()
            session.save(update_fields=['ended_at'])
        return session


def confirm_results(session_id, actor):
    require_manager(actor)
    with transaction.atomic():
        session = Skirmish.objects.select_for_update().get(pk=session_id)
        if session.active:
            raise ValidationError('Сначала завершите замес.')
        if not session.reviewed_at:
            session.reviewed_at, session.reviewed_by = timezone.now(), actor
            session.save(update_fields=['reviewed_at', 'reviewed_by'])
        return session


def correct_attendance(session_id, actor, user, value, reason):
    """Меняет итог участия, сохраняя исходные минуты TS и историю решения."""
    require_manager(actor)
    reason = reason.strip()
    if not reason or len(reason) > 500:
        raise ValidationError('Укажите причину корректировки, до 500 символов.')
    if value is not None and type(value) is not bool:
        raise ValidationError('Выберите результат участия.')
    with transaction.atomic():
        session = Skirmish.objects.select_for_update().get(pk=session_id)
        if session.active or session.reviewed_at:
            raise ValidationError('Корректировка доступна после завершения и до подтверждения итогов.')
        participant = Participant.objects.filter(skirmish=session, user=user).first()
        if participant is None:
            if not user.is_active or not is_guild_member(user):
                raise ValidationError('Добавить можно только действующего члена гильдии.')
            participant = Participant.objects.create(skirmish=session, user=user)
        if participant.attendance_override != value:
            AttendanceCorrection.objects.create(participant=participant, actor=actor,
                previous_value=participant.attendance_override, new_value=value, reason=reason)
            participant.attendance_override = value
            participant.save(update_fields=['attendance_override'])
        return participant
