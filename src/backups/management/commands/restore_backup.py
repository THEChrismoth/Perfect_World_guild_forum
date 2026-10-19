import tempfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.template.defaultfilters import filesizeformat

from backups.models import BackupSettings
from backups.services import BackupError, backup_dir, list_archives, restore_backup, sync_journal_with_files
from backups.yandex import YandexDisk, YandexDiskError


class Command(BaseCommand):
    help = ('Восстанавливает сайт из резервной копии. ВНИМАНИЕ: текущие данные будут заменены. '
            'Без аргументов показывает список копий на сервере')

    def add_arguments(self, parser):
        parser.add_argument('file', nargs='?', help='Имя файла копии (из папки копий на сервере) или путь к файлу')
        parser.add_argument('--from-yandex', action='store_true',
                            help='Скачать копию с этим именем из папки на Яндекс Диске')
        parser.add_argument('--no-media', action='store_true', help='Не восстанавливать загруженные файлы')
        parser.add_argument('--yes', action='store_true', help='Не спрашивать подтверждение')

    def handle(self, *args, **options):
        if not options['file']:
            self.list_backups()
            return

        name = options['file']
        if not options['yes']:
            self.stdout.write(self.style.WARNING(
                f'Все текущие данные сайта будут заменены данными из копии {name}.'
            ))
            if input('Продолжить? Введите "да": ').strip().lower() not in ('да', 'yes', 'y'):
                self.stdout.write('Отменено')
                return

        with tempfile.TemporaryDirectory() as tmp:
            if options['from_yandex']:
                path = self.download_from_yandex(name, Path(tmp))
            else:
                path = Path(name)
                if not path.is_absolute() and not path.exists():
                    path = backup_dir() / name

            try:
                manifest = restore_backup(path, restore_media=not options['no_media'], log=self.stdout.write)
            except BackupError as error:
                raise CommandError(str(error)) from None

        sync_journal_with_files()

        self.stdout.write(self.style.SUCCESS(f'Восстановлено из копии от {manifest["created_at"]}'))
        self.stdout.write('Перезапустите сайт: docker compose restart web')

    def list_backups(self):
        files = list_archives()
        if not files:
            self.stdout.write('На сервере нет резервных копий')
            return
        self.stdout.write('Копии на сервере (новые сверху, 🔒 — зашифрована):')
        for path in files:
            lock = '🔒 ' if path.name.endswith('.gpg') else '   '
            self.stdout.write(f'  {lock}{path.name}  {filesizeformat(path.stat().st_size)}')
        self.stdout.write('\nВосстановить: python manage.py restore_backup <имя файла>')

    def download_from_yandex(self, name, target_dir):
        backup_settings = BackupSettings.load()
        token = backup_settings.get_yandex_token()
        if not token:
            raise CommandError('Токен Яндекс Диска не настроен в админ-панели (или не расшифровывается после смены '
                               'DJANGO_SECRET_KEY). На новом сервере введите токен в настройках резервных копий')
        remote = backup_settings.yandex_folder.rstrip('/') + '/' + name
        local = target_dir / name
        self.stdout.write(f'Скачиваю {remote}...')
        try:
            YandexDisk(token).download(remote, local)
        except YandexDiskError as error:
            raise CommandError(str(error)) from None
        return local
