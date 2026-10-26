"""Периодический сброс демо-сайта к исходным данным (demo_seed).

Работает в фоне контейнера демо (docker/demo/entrypoint.sh). Сброс выходит из всех аккаунтов,
поэтому делается, когда посетителей нет: прошло --hours часов и гости не заходили --idle-minutes минут.
Если посетители идут без перерыва, база все равно сбрасывается через двойной интервал.
"""
import datetime
import logging
import time

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from demo.accounts import GUEST_GROUP
from profiles.models import Profile

logger = logging.getLogger(__name__)


def should_reset(elapsed, interval, visitors_active):
    """elapsed и interval — timedelta с прошлого сброса и между сбросами."""
    if elapsed < interval:
        return False
    return elapsed >= 2 * interval or not visitors_active


def visitors_active(idle):
    since = timezone.now() - idle
    return Profile.objects.filter(last_activity__gte=since, user__groups__name=GUEST_GROUP).exists()


class Command(BaseCommand):
    help = 'Периодически сбрасывает демо-сайт к исходным данным (только при DEMO_MODE=True)'

    def add_arguments(self, parser):
        parser.add_argument('--hours', type=float, default=6, help='Как часто сбрасывать, часов (по умолчанию 6)')
        parser.add_argument('--idle-minutes', type=int, default=10,
                            help='Сколько минут без посетителей ждать перед сбросом (по умолчанию 10)')
        parser.add_argument('--check-minutes', type=int, default=5, help='Как часто проверять, минут')

    def handle(self, *args, **options):
        if not settings.DEMO_MODE:
            raise CommandError('Сброс стирает всю базу, поэтому работает только при DEMO_MODE=True')

        interval = datetime.timedelta(hours=options['hours'])
        idle = datetime.timedelta(minutes=options['idle_minutes'])
        # Контейнер стартует с только что заполненной базой — отсчет от запуска.
        last_reset = time.monotonic()
        self.stdout.write(f'Сброс демо каждые {options["hours"]:g} ч, после {options["idle_minutes"]} мин без посетителей')

        while True:
            time.sleep(options['check_minutes'] * 60)
            elapsed = datetime.timedelta(seconds=time.monotonic() - last_reset)
            try:
                if should_reset(elapsed, interval, visitors_active(idle)):
                    call_command('demo_seed', stdout=self.stdout)
                    last_reset = time.monotonic()
            except Exception:
                # Сбой одного сброса не должен останавливать расписание.
                logger.exception('Не удалось сбросить демо')
