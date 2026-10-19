import datetime
import io
import json
import shutil
import sqlite3
import tarfile
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from notifications.models import Notification
from . import crypto, services
from .models import Backup, BackupSettings
from .yandex import YandexDisk, YandexDiskError


def fake_encrypt(source, target, password=None):
    """Подмена gpg в тестах: «шифрованный» файл — копия с меткой в начале"""
    Path(target).write_bytes(b'FAKE-GPG' + Path(source).read_bytes())


def fake_decrypt(source, target, password=None):
    data = Path(source).read_bytes()
    if not data.startswith(b'FAKE-GPG'):
        raise crypto.EncryptionError('Неверный пароль шифрования')
    Path(target).write_bytes(data[len(b'FAKE-GPG'):])


def gpg_works():
    """Настоящий gpg доступен и умеет шифровать (в Docker — да; gpg из Git для Windows — не всегда)"""
    with tempfile.TemporaryDirectory() as tmp:
        source, target, back = Path(tmp) / 'a', Path(tmp) / 'a.gpg', Path(tmp) / 'b'
        source.write_bytes(b'probe')
        try:
            crypto.encrypt_file(source, target, password='probe')
            crypto.decrypt_file(target, back, password='probe')
        except crypto.EncryptionError:
            return False
        return back.read_bytes() == b'probe'


ENCRYPTED = override_settings(BACKUP_ENCRYPTION_PASSWORD='test-password')


class TempDirsMixin:
    """Копии и media пишутся во временные папки, а не в настоящие"""

    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.backup_dir = self.tmp / 'backups'
        self.media_root = self.tmp / 'media'
        (self.media_root / 'avatars').mkdir(parents=True)
        (self.media_root / 'avatars' / 'a.png').write_bytes(b'png')
        overrides = override_settings(BACKUP_DIR=str(self.backup_dir), MEDIA_ROOT=str(self.media_root))
        overrides.enable()
        self.addCleanup(overrides.disable)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)


def moscow(*args):
    return timezone.make_aware(datetime.datetime(*args))


class ScheduleTests(TestCase):
    def make_settings(self, **kwargs):
        defaults = dict(enabled=True, frequency='daily', run_time=datetime.time(4, 0))
        defaults.update(kwargs)
        return BackupSettings(**defaults)

    def test_daily_due_after_time(self):
        s = self.make_settings(last_scheduled_run=moscow(2026, 10, 18, 4, 0, 30))
        self.assertFalse(services.is_backup_due(s, moscow(2026, 10, 19, 3, 59)))
        self.assertTrue(services.is_backup_due(s, moscow(2026, 10, 19, 4, 0)))

    def test_not_due_twice_same_day(self):
        s = self.make_settings(last_scheduled_run=moscow(2026, 10, 19, 4, 0, 30))
        self.assertFalse(services.is_backup_due(s, moscow(2026, 10, 19, 23, 0)))

    def test_weekly(self):
        # 19.10.2026 — понедельник
        s = self.make_settings(frequency='weekly', weekday=2, last_scheduled_run=moscow(2026, 10, 14, 4, 1))
        self.assertFalse(services.is_backup_due(s, moscow(2026, 10, 20, 12, 0)))  # вторник
        self.assertTrue(services.is_backup_due(s, moscow(2026, 10, 21, 4, 0)))   # среда

    def test_disabled_or_just_enabled(self):
        self.assertFalse(services.is_backup_due(self.make_settings(enabled=False, last_scheduled_run=moscow(2020, 1, 1, 0, 0))))
        self.assertFalse(services.is_backup_due(self.make_settings(last_scheduled_run=None)))


class CreateBackupTests(TempDirsMixin, TransactionTestCase):
    def test_archive_contains_database_media_and_manifest(self):
        User.objects.create_user('alice')

        backup = services.run_backup(Backup.objects.create())

        self.assertEqual(backup.status, 'success', backup.error)
        self.assertTrue(backup.local_available)
        self.assertGreater(backup.size, 0)
        with tarfile.open(backup.local_path) as archive:
            names = archive.getnames()
            manifest = json.load(archive.extractfile('manifest.json'))
            self.assertIn('media/avatars/a.png', names)
            self.assertIn(manifest['database_file'], names)
            if settings.DATABASES['default']['ENGINE'] != 'django.db.backends.sqlite3':
                # PostgreSQL (тесты в Docker): дамп pg_dump в формате custom начинается с PGDMP
                self.assertEqual(manifest['database_engine'], 'postgresql')
                self.assertEqual(archive.extractfile('database.dump').read(5), b'PGDMP')
                return
            db_bytes = archive.extractfile('database.sqlite3').read()
        self.assertEqual(manifest['database_engine'], 'sqlite')

        # В копии базы есть созданный пользователь
        db_path = self.tmp / 'check.sqlite3'
        db_path.write_bytes(db_bytes)
        with sqlite3.connect(db_path) as conn:
            usernames = [row[0] for row in conn.execute('SELECT username FROM auth_user')]
        self.assertIn('alice', usernames)

    def test_without_media(self):
        s = BackupSettings.load()
        s.include_media = False
        s.save()

        backup = services.run_backup(Backup.objects.create())

        with tarfile.open(backup.local_path) as archive:
            self.assertFalse(any(name.startswith('media') for name in archive.getnames()))

    def test_rotation_keeps_n_latest(self):
        s = BackupSettings.load()
        s.keep_local = 2
        s.save()

        backups = []
        for i in range(4):
            # Разные имена файлов, как будто копии сделаны в разное время
            with mock.patch('backups.services.timezone.localtime',
                            return_value=moscow(2026, 10, 19, 4, 0, i)):
                backups.append(services.run_backup(Backup.objects.create()))

        files = sorted(p.name for p in self.backup_dir.glob('*.tar.gz'))
        self.assertEqual(files, sorted([backups[2].file_name, backups[3].file_name]))
        for backup in backups[:2]:
            backup.refresh_from_db()
            self.assertTrue(backup.local_deleted)

    def test_failure_is_logged_and_admins_notified(self):
        User.objects.create_superuser('admin', password='pass')
        with mock.patch('backups.services._dump_database', side_effect=services.BackupError('диск переполнен')):
            backup = services.run_backup(Backup.objects.create())

        self.assertEqual(backup.status, 'failed')
        self.assertIn('диск переполнен', backup.error)
        self.assertTrue(Notification.objects.filter(user__username='admin', notification_type='error').exists())

    def test_deleting_log_entry_deletes_file(self):
        backup = services.run_backup(Backup.objects.create())
        path = backup.local_path

        backup.delete()

        self.assertFalse(path.exists())

    def test_journal_synced_after_restore(self):
        backup = services.run_backup(Backup.objects.create())
        # Как будто восстановили базу из копии: записи о файле нет, а копия «выполняется»
        Backup.objects.filter(pk=backup.pk).update(file_name='', status='running')

        services.sync_journal_with_files()

        self.assertEqual(Backup.objects.get(pk=backup.pk).status, 'failed')
        restored = Backup.objects.get(file_name=backup.file_name)
        self.assertEqual(restored.status, 'success')
        self.assertTrue(restored.local_available)

    def test_interrupted_backups_marked_failed(self):
        Backup.objects.create(status='running')

        services.recover_interrupted()

        self.assertEqual(Backup.objects.get().status, 'failed')


@ENCRYPTED
@mock.patch('backups.services.encrypt_file', fake_encrypt)
class YandexUploadTests(TempDirsMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        s = BackupSettings.load()
        s.yandex_enabled = True
        s.yandex_token = 'token'
        s.keep_yandex = 2
        s.save()

    def test_unencrypted_copy_not_uploaded(self):
        with override_settings(BACKUP_ENCRYPTION_PASSWORD=''), \
                mock.patch.object(YandexDisk, 'upload') as upload:
            backup = services.run_backup(Backup.objects.create())

        upload.assert_not_called()
        self.assertEqual(backup.status, 'warning')
        self.assertEqual(backup.yandex_status, 'failed')
        self.assertIn('не зашифрована', backup.error)
        self.assertFalse(backup.encrypted)

    def test_uploaded_and_old_copies_removed(self):
        remote_files = [
            {'name': f'backup-2026101{i}-040000.tar.gz', 'path': f'app:/backups/backup-2026101{i}-040000.tar.gz', 'type': 'file'}
            for i in range(4)
        ] + [{'name': 'notes.txt', 'path': 'app:/backups/notes.txt', 'type': 'file'}]

        with mock.patch.object(YandexDisk, 'ensure_folder') as ensure_folder, \
                mock.patch.object(YandexDisk, 'upload') as upload, \
                mock.patch.object(YandexDisk, 'list_files', return_value=remote_files), \
                mock.patch.object(YandexDisk, 'delete') as delete:
            backup = services.run_backup(Backup.objects.create())

        self.assertEqual(backup.status, 'success', backup.error)
        self.assertTrue(backup.encrypted)
        self.assertTrue(backup.file_name.endswith('.tar.gz.gpg'))
        self.assertEqual(backup.yandex_status, 'uploaded')
        self.assertEqual(backup.yandex_path, f'app:/backups/{backup.file_name}')
        ensure_folder.assert_called_once_with('app:/backups')
        # На Диск уходит именно зашифрованный файл
        uploaded_path = upload.call_args.args[0]
        self.assertTrue(Path(uploaded_path).read_bytes().startswith(b'FAKE-GPG'))
        # Остаются две самые новые копии, чужие файлы не трогаем
        deleted = sorted(call.args[0] for call in delete.call_args_list)
        self.assertEqual(deleted, ['app:/backups/backup-20261010-040000.tar.gz', 'app:/backups/backup-20261011-040000.tar.gz'])

    def test_upload_error_keeps_local_copy(self):
        with mock.patch.object(YandexDisk, 'ensure_folder', side_effect=YandexDiskError('Токен недействителен')):
            backup = services.run_backup(Backup.objects.create())

        self.assertEqual(backup.status, 'warning')
        self.assertEqual(backup.yandex_status, 'failed')
        self.assertIn('Токен недействителен', backup.error)
        self.assertTrue(backup.local_available)

        # Копия с ошибкой загрузки на Диск не удаляется ротацией раньше времени
        s = BackupSettings.load()
        s.yandex_enabled = False
        s.keep_local = 2
        s.save()
        services.rotate_local(2)
        backup.refresh_from_db()
        self.assertFalse(backup.local_deleted)


@ENCRYPTED
@mock.patch('backups.services.encrypt_file', fake_encrypt)
@mock.patch('backups.services.decrypt_file', fake_decrypt)
class EncryptedBackupTests(TempDirsMixin, TransactionTestCase):
    def test_no_plain_archive_in_backup_dir(self):
        backup = services.run_backup(Backup.objects.create())

        self.assertEqual(backup.status, 'success', backup.error)
        self.assertEqual([p.name for p in self.backup_dir.iterdir()], [backup.file_name])
        self.assertTrue(backup.local_path.read_bytes().startswith(b'FAKE-GPG'))

    def test_restore_encrypted(self):
        backup = services.run_backup(Backup.objects.create())
        (self.media_root / 'avatars' / 'a.png').unlink()

        # Саму базу не трогаем: подменяем и SQLite, и pg_restore (в Docker тесты идут на PostgreSQL)
        with mock.patch('backups.services.connection'), \
                mock.patch('backups.services.sqlite3.connect') as connect, \
                mock.patch('backups.services.subprocess.run', return_value=mock.Mock(returncode=0)) as run:
            services.restore_backup(backup.local_path, log=lambda *_: None)

        self.assertTrue(connect.called or run.called)
        self.assertEqual((self.media_root / 'avatars' / 'a.png').read_bytes(), b'png')

    def test_restore_wrong_password(self):
        backup = services.run_backup(Backup.objects.create())
        backup.local_path.write_bytes(b'garbage')

        with self.assertRaisesRegex(services.BackupError, 'Неверный пароль'):
            services.restore_backup(backup.local_path)


class SecretFieldTests(TestCase):
    def test_token_stored_encrypted(self):
        s = BackupSettings.load()
        s.yandex_token = 'y0_AgAAAA-secret'
        s.save()

        raw = BackupSettings.objects.values_list('yandex_token', flat=True).get()
        self.assertTrue(raw.startswith(crypto.SECRET_PREFIX))
        self.assertNotIn('secret', raw)
        self.assertEqual(BackupSettings.load().get_yandex_token(), 'y0_AgAAAA-secret')

    def test_unreadable_after_secret_key_change(self):
        s = BackupSettings.load()
        s.yandex_token = 'y0_token'
        s.save()

        with override_settings(SECRET_KEY='another-secret-key-' * 3):
            s = BackupSettings.load()
            self.assertEqual(s.get_yandex_token(), '')
            self.assertTrue(s.yandex_token_unreadable)
            self.assertFalse(BackupSettings(yandex_enabled=True, yandex_token=s.yandex_token).yandex_configured)


@unittest.skipUnless(gpg_works(), 'gpg недоступен — проверяется в Docker: docker compose exec web python manage.py test backups')
class RealGpgTests(TestCase):
    def test_round_trip_and_wrong_password(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target, back = Path(tmp) / 'a.tar.gz', Path(tmp) / 'a.tar.gz.gpg', Path(tmp) / 'b'
            source.write_bytes(b'secret data' * 1000)

            crypto.encrypt_file(source, target, password='right')
            self.assertNotIn(b'secret data', target.read_bytes())

            crypto.decrypt_file(target, back, password='right')
            self.assertEqual(back.read_bytes(), source.read_bytes())

            with self.assertRaisesRegex(crypto.EncryptionError, 'Неверный пароль'):
                crypto.decrypt_file(target, Path(tmp) / 'c', password='wrong')


class YandexClientTests(TestCase):
    def test_unauthorized_message(self):
        error = urllib.error.HTTPError('https://x', 401, 'Unauthorized', {}, io.BytesIO(b'{"description": "Unauthorized"}'))
        with mock.patch('backups.yandex.urllib.request.urlopen', side_effect=error):
            with self.assertRaisesRegex(YandexDiskError, 'Токен Яндекса недействителен'):
                YandexDisk('bad').check()

    def test_existing_folder_is_not_error(self):
        error = urllib.error.HTTPError('https://x', 409, 'Conflict', {}, io.BytesIO(b'{}'))
        with mock.patch('backups.yandex.urllib.request.urlopen', side_effect=error) as urlopen:
            YandexDisk('token').ensure_folder('app:/backups/guild')
        urls = [call.args[0].full_url for call in urlopen.call_args_list]
        self.assertEqual(len(urls), 2)
        self.assertIn('path=app%3A%2Fbackups%2Fguild', urls[1])


class RestoreTests(TempDirsMixin, TestCase):
    def make_archive(self):
        work = self.tmp / 'work'
        (work / 'media' / 'posts').mkdir(parents=True)
        (work / 'media' / 'posts' / 'restored.png').write_bytes(b'restored')
        with sqlite3.connect(work / 'database.sqlite3') as conn:
            conn.execute('CREATE TABLE marker (value TEXT)')
            conn.execute("INSERT INTO marker VALUES ('from backup')")
        (work / 'manifest.json').write_text(json.dumps({
            'created_at': '2026-10-19T04:00:00+03:00',
            'database_engine': 'sqlite',
            'database_file': 'database.sqlite3',
            'includes_media': True,
        }))
        archive_path = self.tmp / 'backup-test.tar.gz'
        with tarfile.open(archive_path, 'w:gz') as archive:
            for name in ('manifest.json', 'database.sqlite3', 'media'):
                archive.add(work / name, arcname=name)
        return archive_path

    def test_restore_sqlite_and_media(self):
        target_db = self.tmp / 'site.sqlite3'
        sqlite3.connect(target_db).close()

        # Подменяем базу, чтобы не трогать тестовую базу Django (в Docker это PostgreSQL)
        with mock.patch.dict(settings.DATABASES['default'],
                             {'ENGINE': 'django.db.backends.sqlite3', 'NAME': str(target_db)}), \
                mock.patch('backups.services.connection'):
            services.restore_backup(self.make_archive(), log=lambda *_: None)

        with sqlite3.connect(target_db) as conn:
            self.assertEqual(conn.execute('SELECT value FROM marker').fetchone()[0], 'from backup')
        self.assertEqual((self.media_root / 'posts' / 'restored.png').read_bytes(), b'restored')
        # Старые файлы заменены содержимым копии
        self.assertFalse((self.media_root / 'avatars' / 'a.png').exists())

    def test_not_a_backup(self):
        bad = self.tmp / 'bad.tar.gz'
        with tarfile.open(bad, 'w:gz') as archive:
            info = tarfile.TarInfo('readme.txt')
            archive.addfile(info, io.BytesIO(b''))
        with self.assertRaisesRegex(services.BackupError, 'manifest.json'):
            services.restore_backup(bad)


@override_settings(SECURE_SSL_REDIRECT=False)
class BackupAdminTests(TempDirsMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser('admin', password='pass')
        self.staff = User.objects.create_user('officer', password='pass', is_staff=True)

    def test_run_button_queues_backup(self):
        self.client.force_login(self.admin)

        response = self.client.post(reverse('admin:backups_backup_run'))

        self.assertRedirects(response, reverse('admin:backups_backup_changelist'))
        backup = Backup.objects.get()
        self.assertEqual(backup.status, 'pending')
        self.assertEqual(backup.requested_by, self.admin)

    def test_scheduler_runs_queued_backup(self):
        Backup.objects.create(trigger='manual')
        command = __import__('backups.management.commands.run_backup_scheduler', fromlist=['Command']).Command()
        command.running = True

        command.tick()

        self.assertEqual(Backup.objects.get().status, 'success')

    def test_download_only_for_superuser(self):
        backup = services.run_backup(Backup.objects.create())
        url = reverse('admin:backups_backup_download', args=[backup.pk])

        self.client.force_login(self.staff)
        self.assertNotEqual(self.client.get(url).status_code, 200)

        self.client.force_login(self.admin)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(backup.file_name, response['Content-Disposition'])

    def test_pages_render(self):
        self.client.force_login(self.admin)
        services.run_backup(Backup.objects.create())
        settings_url = reverse('admin:backups_backupsettings_change', args=[BackupSettings.load().pk])

        self.assertEqual(self.client.get(reverse('admin:backups_backup_changelist')).status_code, 200)
        self.assertEqual(self.client.get(settings_url).status_code, 200)

    SETTINGS_FORM = {
        'enabled': 'on', 'frequency': 'daily', 'weekday': '0', 'run_time': '04:00',
        'include_media': 'on', 'keep_local': '7',
        'yandex_enabled': 'on', 'yandex_token': '', 'yandex_folder': 'app:/backups', 'keep_yandex': '30',
    }

    @ENCRYPTED
    def test_token_kept_when_field_left_empty(self):
        s = BackupSettings.load()
        s.yandex_token = 'secret-token'
        s.save()
        self.client.force_login(self.admin)
        url = reverse('admin:backups_backupsettings_change', args=[s.pk])

        response = self.client.get(url)
        self.assertNotContains(response, 'secret-token')
        self.assertContains(response, 'Включено')

        self.client.post(url, self.SETTINGS_FORM)
        s.refresh_from_db()
        self.assertEqual(s.get_yandex_token(), 'secret-token')
        self.assertTrue(s.yandex_token.startswith(crypto.SECRET_PREFIX))
        self.assertTrue(s.enabled)

    @ENCRYPTED
    def test_new_token_saved_encrypted(self):
        self.client.force_login(self.admin)
        url = reverse('admin:backups_backupsettings_change', args=[BackupSettings.load().pk])

        self.client.post(url, {**self.SETTINGS_FORM, 'yandex_token': 'y0_new-token'})

        s = BackupSettings.load()
        self.assertEqual(s.get_yandex_token(), 'y0_new-token')
        self.assertNotIn('new-token', s.yandex_token)

    @override_settings(BACKUP_ENCRYPTION_PASSWORD='')
    def test_yandex_requires_encryption(self):
        self.client.force_login(self.admin)
        url = reverse('admin:backups_backupsettings_change', args=[BackupSettings.load().pk])

        response = self.client.post(url, {**self.SETTINGS_FORM, 'yandex_token': 'y0_token'})

        self.assertContains(response, 'только для зашифрованных копий')
        self.assertFalse(BackupSettings.load().yandex_enabled)


class BackupNowCommandTests(TempDirsMixin, TransactionTestCase):
    def test_creates_backup(self):
        out = io.StringIO()
        call_command('backup_now', stdout=out)

        self.assertEqual(Backup.objects.get().status, 'success')
        self.assertIn('Готово', out.getvalue())
