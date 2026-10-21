import signal
import time

from django.core.management.base import BaseCommand
from django.db import DatabaseError, close_old_connections
from django.utils import timezone

from backups.models import Backup, BackupSettings
from backups.services import is_backup_due, recover_interrupted, run_backup

CHECK_INTERVAL = 30  # Секунд


class Command(BaseCommand):
    help = ('Планировщик резервных копий: создает копии по расписанию из админ-панели '
            'и выполняет копии, запрошенные кнопкой «Сделать копию сейчас». Работает постоянно')

    def handle(self, *args, **options):
        self.running = True
        signal.signal(signal.SIGTERM, self._stop)
        signal.signal(signal.SIGINT, self._stop)

        self.stdout.write('Планировщик резервных копий запущен')
        recovered = False

        while self.running:
            close_old_connections()
            try:
                if not recovered:
                    recover_interrupted()
                    recovered = True
                self.tick()
            except DatabaseError as error:
                # База еще не готова или миграции не применены — подождем.
                self.stderr.write(f'База данных недоступна: {error}')
            except Exception as error:
                self.stderr.write(f'Ошибка планировщика: {error}')

            for _ in range(CHECK_INTERVAL):
                if not self.running:
                    break
                time.sleep(1)

        self.stdout.write('Планировщик резервных копий остановлен')

    def tick(self):
        backup_settings = BackupSettings.load()

        # Первое включение расписания: запоминаем момент, первая копия — в ближайшее время по расписанию.
        if backup_settings.enabled and backup_settings.last_scheduled_run is None:
            backup_settings.last_scheduled_run = timezone.now()
            backup_settings.save(update_fields=['last_scheduled_run'])

        if is_backup_due(backup_settings):
            backup_settings.last_scheduled_run = timezone.now()
            backup_settings.save(update_fields=['last_scheduled_run'])
            Backup.objects.create(trigger='schedule')

        # Выполняем все копии из очереди: и по расписанию, и запрошенные вручную.
        for backup in Backup.objects.filter(status='pending').order_by('created_at'):
            if not self.running:
                break
            self.stdout.write(f'Создаю резервную копию #{backup.pk}...')
            run_backup(backup)
            self.stdout.write(f'Копия #{backup.pk}: {backup.get_status_display()} {backup.file_name}')

    def _stop(self, signum, frame):
        self.running = False
