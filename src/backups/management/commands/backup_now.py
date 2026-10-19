from django.core.management.base import BaseCommand, CommandError
from django.template.defaultfilters import filesizeformat

from backups.models import Backup
from backups.services import run_backup


class Command(BaseCommand):
    help = 'Сразу создает резервную копию с текущими настройками (локально и, если настроено, на Яндекс Диск)'

    def handle(self, *args, **options):
        self.stdout.write('Создаю резервную копию...')
        backup = run_backup(Backup.objects.create(trigger='manual'))

        if backup.status == 'failed':
            raise CommandError(backup.error)

        self.stdout.write(self.style.SUCCESS(f'Готово: {backup.local_path} ({filesizeformat(backup.size or 0)})'))
        if backup.yandex_status == 'uploaded':
            self.stdout.write(self.style.SUCCESS(f'Загружено на Яндекс Диск: {backup.yandex_path}'))
        if backup.error:
            self.stdout.write(self.style.WARNING(backup.error))
