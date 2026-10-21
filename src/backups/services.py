"""Создание, хранение и восстановление резервных копий.

Копия — архив backup-ГГГГММДД-ЧЧММСС.tar.gz:
    manifest.json        — дата, тип базы, что внутри
    database.dump        — дамп PostgreSQL (pg_dump, формат custom)  или
    database.sqlite3     — копия базы SQLite
    media/...            — загруженные файлы (если включено)

Если в .env задан BACKUP_ENCRYPTION_PASSWORD, архив шифруется GPG и сохраняется как
backup-ГГГГММДД-ЧЧММСС.tar.gz.gpg. Незашифрованный архив при этом не попадает в папку копий
даже временно. На Яндекс Диск загружаются только зашифрованные копии.
"""
import datetime
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

from .crypto import ENCRYPTED_SUFFIX, EncryptionError, decrypt_file, encrypt_file, encryption_enabled
from .models import Backup, BackupSettings
from .yandex import YandexDisk, YandexDiskError

ARCHIVE_PREFIX = 'backup-'
ARCHIVE_SUFFIX = '.tar.gz'
ENCRYPTED_ARCHIVE_SUFFIX = ARCHIVE_SUFFIX + ENCRYPTED_SUFFIX
PARTIAL_SUFFIX = '.part'


def is_archive_name(name):
    return name.startswith(ARCHIVE_PREFIX) and name.endswith((ARCHIVE_SUFFIX, ENCRYPTED_ARCHIVE_SUFFIX))


def list_archives():
    """Файлы копий на сервере, новые первыми."""
    return sorted((p for p in backup_dir().iterdir() if p.is_file() and is_archive_name(p.name)), reverse=True)


class BackupError(Exception):
    pass


def backup_dir():
    path = Path(settings.BACKUP_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------- Расписание ----------

def last_due_time(backup_settings, now=None):
    """Последний момент, когда по расписанию должна была создаться копия."""
    now = timezone.localtime(now or timezone.now())
    due = now.replace(
        hour=backup_settings.run_time.hour,
        minute=backup_settings.run_time.minute,
        second=0,
        microsecond=0,
    )
    if backup_settings.frequency == 'weekly':
        due -= datetime.timedelta(days=(due.weekday() - backup_settings.weekday) % 7)
        if due > now:
            due -= datetime.timedelta(days=7)
    elif due > now:
        due -= datetime.timedelta(days=1)
    return due


def is_backup_due(backup_settings, now=None):
    if not backup_settings.enabled:
        return False
    if backup_settings.last_scheduled_run is None:
        # Расписание только что включили: первая копия — в ближайшее время по расписанию.
        return False
    return backup_settings.last_scheduled_run < last_due_time(backup_settings, now)


# ---------- Создание ----------

def _dump_database(target_dir):
    db = settings.DATABASES['default']
    engine = db['ENGINE']

    if engine == 'django.db.backends.postgresql':
        path = target_dir / 'database.dump'
        env = os.environ.copy()
        if db.get('PASSWORD'):
            env['PGPASSWORD'] = str(db['PASSWORD'])
        command = ['pg_dump', '--format=custom', '--no-owner', '--no-privileges', f'--file={path}']
        if db.get('HOST'):
            command.append(f'--host={db["HOST"]}')
        if db.get('PORT'):
            command.append(f'--port={db["PORT"]}')
        if db.get('USER'):
            command.append(f'--username={db["USER"]}')
        command.append(db['NAME'])
        try:
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=3600)
        except FileNotFoundError:
            raise BackupError('Не найдена программа pg_dump. Установите клиент PostgreSQL') from None
        if result.returncode != 0:
            raise BackupError(f'pg_dump завершился с ошибкой: {result.stderr.strip()}')
        return 'postgresql', path.name

    if engine == 'django.db.backends.sqlite3':
        path = target_dir / 'database.sqlite3'
        # Внутри открытой транзакции SQLite не отдаст копию и будет ждать бесконечно.
        if connection.in_atomic_block:
            raise BackupError('Копию SQLite нельзя создать внутри транзакции')
        # Встроенный механизм SQLite дает целостную копию даже при работающем сайте.
        connection.ensure_connection()
        destination = sqlite3.connect(path)
        try:
            connection.connection.backup(destination)
        finally:
            destination.close()
        return 'sqlite', path.name

    raise BackupError(f'Резервное копирование базы {engine} не поддерживается')


def _build_archive(backup, include_media):
    """Создает архив копии. Возвращает (путь к файлу, зашифрован ли он)."""
    encrypt = encryption_enabled()
    timestamp = timezone.localtime().strftime('%Y%m%d-%H%M%S')
    suffix = ENCRYPTED_ARCHIVE_SUFFIX if encrypt else ARCHIVE_SUFFIX
    archive_path = backup_dir() / f'{ARCHIVE_PREFIX}{timestamp}{suffix}'
    # Пишем во временный файл: недописанный архив не попадет в список копий.
    partial_path = archive_path.with_name(archive_path.name + PARTIAL_SUFFIX)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        engine, db_file = _dump_database(tmp_dir)

        manifest = {
            'created_at': timezone.now().isoformat(),
            'database_engine': engine,
            'database_file': db_file,
            'includes_media': include_media,
            'backup_id': backup.pk,
        }
        (tmp_dir / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')

        # Незашифрованный архив собираем во временной папке, а не в папке копий.
        plain_path = tmp_dir / 'archive.tar.gz'
        with tarfile.open(plain_path, 'w:gz') as archive:
            archive.add(tmp_dir / 'manifest.json', arcname='manifest.json')
            archive.add(tmp_dir / db_file, arcname=db_file)
            media_root = Path(settings.MEDIA_ROOT)
            if include_media and media_root.exists():
                archive.add(media_root, arcname='media')

        try:
            if encrypt:
                encrypt_file(plain_path, partial_path)
            else:
                shutil.move(plain_path, partial_path)
        except Exception:
            partial_path.unlink(missing_ok=True)
            raise

    # Файл копии может читать только владелец (пользователь сайта).
    partial_path.chmod(0o600)
    partial_path.replace(archive_path)
    return archive_path, encrypt


def run_backup(backup):
    """Выполняет резервное копирование для записи журнала. Ошибки записываются в журнал."""
    backup_settings = BackupSettings.load()
    backup.status = 'running'
    backup.started_at = timezone.now()
    backup.includes_media = backup_settings.include_media
    backup.error = ''
    backup.save()

    try:
        archive_path, encrypted = _build_archive(backup, backup_settings.include_media)
    except Exception as error:
        _fail(backup, f'Не удалось создать копию: {error}')
        return backup

    backup.file_name = archive_path.name
    backup.size = archive_path.stat().st_size
    backup.encrypted = encrypted
    backup.save(update_fields=['file_name', 'size', 'encrypted'])

    errors = []
    if backup_settings.yandex_configured and not encrypted:
        # Данные пользователей не отправляем в чужое облако открытым текстом.
        backup.yandex_status = 'failed'
        errors.append('Яндекс Диск: копия не загружена, потому что не зашифрована. '
                      'Задайте BACKUP_ENCRYPTION_PASSWORD в .env и перезапустите контейнеры')
    elif backup_settings.yandex_configured:
        try:
            remote_path = _upload_to_yandex(backup_settings, archive_path)
        except YandexDiskError as error:
            backup.yandex_status = 'failed'
            errors.append(f'Яндекс Диск: {error}')
        else:
            backup.yandex_status = 'uploaded'
            backup.yandex_path = remote_path

    # Архив на сервере готов — копия считается созданной, даже если с Диском что-то не так.
    # Статус сохраняем до ротации, чтобы текущая копия учитывалась в числе хранимых.
    backup.status = 'success'
    backup.save()

    try:
        rotate_local(backup_settings.keep_local)
    except OSError as error:
        errors.append(f'Не удалось удалить старые копии на сервере: {error}')

    if backup.yandex_status == 'uploaded':
        try:
            rotate_yandex(backup_settings)
        except YandexDiskError as error:
            errors.append(f'Не удалось удалить старые копии на Яндекс Диске: {error}')

    backup.finished_at = timezone.now()
    if errors:
        backup.status = 'warning'
        backup.error = '\n'.join(errors)
    backup.save()

    if errors:
        # Копия на сервере есть, но что-то пошло не так — сообщаем администраторам.
        _notify_admins(backup)
    return backup


def _fail(backup, message):
    backup.status = 'failed'
    backup.error = message
    backup.finished_at = timezone.now()
    backup.save()
    _notify_admins(backup)


def _notify_admins(backup):
    from django.urls import reverse
    from notifications.utils import send_notification_to_admins

    send_notification_to_admins(
        title='⚠️ Проблема с резервной копией',
        message=f'{backup.created_at:%d.%m.%Y %H:%M}: {backup.error}',
        notification_type='error',
        link=reverse('admin:backups_backup_change', args=[backup.pk]),
    )


# ---------- Хранение ----------

def rotate_local(keep):
    """Оставляет на сервере только keep последних успешных копий."""
    backups = Backup.objects.filter(local_deleted=False).exclude(file_name='').order_by('-created_at')
    kept = 0
    for backup in backups:
        if backup.status in Backup.COMPLETED_STATUSES and kept < keep:
            kept += 1
            continue
        if backup.status in ('pending', 'running'):
            continue
        path = backup.local_path
        if path and path.exists():
            path.unlink()
        backup.local_deleted = True
        backup.save(update_fields=['local_deleted'])


def _remote_path(folder, file_name):
    return folder.rstrip('/') + '/' + file_name


def _upload_to_yandex(backup_settings, archive_path):
    disk = YandexDisk(backup_settings.get_yandex_token())
    disk.ensure_folder(backup_settings.yandex_folder)
    remote_path = _remote_path(backup_settings.yandex_folder, archive_path.name)
    disk.upload(archive_path, remote_path)
    return remote_path


def rotate_yandex(backup_settings):
    """Оставляет на Яндекс Диске только keep_yandex последних копий сайта."""
    disk = YandexDisk(backup_settings.get_yandex_token())
    files = [item for item in disk.list_files(backup_settings.yandex_folder) if is_archive_name(item['name'])]
    # Имя содержит дату, поэтому сортировка по имени — это сортировка по времени.
    files.sort(key=lambda item: item['name'], reverse=True)
    for item in files[backup_settings.keep_yandex:]:
        disk.delete(item['path'])
        Backup.objects.filter(file_name=item['name']).update(yandex_status='deleted')


def recover_interrupted():
    """Копии, которые выполнялись при остановке сервера, помечаем как прерванные."""
    for backup in Backup.objects.filter(status='running'):
        backup.status = 'failed'
        backup.error = 'Копирование прервано: сервер был остановлен или перезапущен'
        backup.finished_at = timezone.now()
        backup.save()
    for partial in backup_dir().glob(f'{ARCHIVE_PREFIX}*{PARTIAL_SUFFIX}'):
        partial.unlink()


def sync_journal_with_files():
    """Сверяет журнал копий с файлами на сервере после восстановления.

    После восстановления журнал копий тоже становится таким, каким был в момент копии:
    копия, из которой восстанавливались, записана в нем как «выполняется», а более новых нет.
    """
    known = set(Backup.objects.exclude(file_name='').values_list('file_name', flat=True))
    for backup in Backup.objects.filter(status__in=('pending', 'running')):
        backup.status = 'failed'
        backup.error = 'Запись из восстановленной копии: копирование тогда еще не завершилось'
        backup.finished_at = backup.finished_at or timezone.now()
        backup.save()

    for path in reversed(list_archives()):
        if path.name in known:
            continue
        Backup.objects.create(
            status='success',
            file_name=path.name,
            size=path.stat().st_size,
            encrypted=path.name.endswith(ENCRYPTED_ARCHIVE_SUFFIX),
            finished_at=timezone.now(),
            error='Файл найден на сервере после восстановления',
        )


# ---------- Восстановление ----------

def restore_backup(archive_path, restore_media=True, log=print):
    """Восстанавливает базу (и загруженные файлы) из архива. Текущие данные заменяются."""
    archive_path = Path(archive_path)
    if not archive_path.exists():
        raise BackupError(f'Файл {archive_path} не найден')

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        if archive_path.name.endswith(ENCRYPTED_SUFFIX):
            log('Расшифровываю копию...')
            plain_path = tmp_dir / 'archive.tar.gz'
            try:
                decrypt_file(archive_path, plain_path)
            except EncryptionError as error:
                raise BackupError(str(error)) from None
            archive_path = plain_path

        try:
            with tarfile.open(archive_path, 'r:gz') as archive:
                archive.extractall(tmp_dir / 'content', filter='data')
        except tarfile.TarError:
            raise BackupError('Файл поврежден или это не резервная копия сайта') from None
        tmp_dir = tmp_dir / 'content'

        manifest_path = tmp_dir / 'manifest.json'
        if not manifest_path.exists():
            raise BackupError('Это не резервная копия сайта: в архиве нет manifest.json')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))

        engine = manifest['database_engine']
        db_file = tmp_dir / manifest['database_file']
        db = settings.DATABASES['default']

        if engine == 'postgresql':
            if db['ENGINE'] != 'django.db.backends.postgresql':
                raise BackupError('Копия сделана из PostgreSQL, а сайт сейчас работает на другой базе')
            log('Восстанавливаю базу данных PostgreSQL...')
            env = os.environ.copy()
            if db.get('PASSWORD'):
                env['PGPASSWORD'] = str(db['PASSWORD'])
            command = ['pg_restore', '--clean', '--if-exists', '--no-owner', '--no-privileges',
                       '--single-transaction', f'--dbname={db["NAME"]}']
            if db.get('HOST'):
                command.append(f'--host={db["HOST"]}')
            if db.get('PORT'):
                command.append(f'--port={db["PORT"]}')
            if db.get('USER'):
                command.append(f'--username={db["USER"]}')
            command.append(str(db_file))
            connection.close()
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            if result.returncode != 0:
                raise BackupError(f'pg_restore завершился с ошибкой: {result.stderr.strip()}')
        elif engine == 'sqlite':
            if db['ENGINE'] != 'django.db.backends.sqlite3':
                raise BackupError('Копия сделана из SQLite, а сайт сейчас работает на PostgreSQL. '
                                  'Перенесите данные через dumpdata/loaddata (см. docs/DEVELOPMENT.md)')
            log('Восстанавливаю базу данных SQLite...')
            connection.close()
            source = sqlite3.connect(db_file)
            destination = sqlite3.connect(db['NAME'])
            try:
                source.backup(destination)
            finally:
                source.close()
                destination.close()
        else:
            raise BackupError(f'Неизвестный тип базы в копии: {engine}')

        media_src = tmp_dir / 'media'
        if restore_media and manifest.get('includes_media') and media_src.exists():
            log('Восстанавливаю загруженные файлы...')
            media_root = Path(settings.MEDIA_ROOT)
            media_root.mkdir(parents=True, exist_ok=True)
            # Очищаем содержимое, а не саму папку: в Docker это точка монтирования тома.
            for child in media_root.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            shutil.copytree(media_src, media_root, dirs_exist_ok=True)

    return manifest
