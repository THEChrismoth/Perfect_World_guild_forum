"""Шифрование резервных копий и секретов.

Архивы шифруются стандартным GPG (OpenPGP, AES-256, ключ из пароля). Поэтому копию можно
расшифровать и без этого сайта: `gpg -d backup-....tar.gz.gpg > backup.tar.gz`
(в Windows — программой Gpg4win).

Пароль шифрования задается в .env (BACKUP_ENCRYPTION_PASSWORD) и намеренно не хранится в базе:
иначе он попадал бы внутрь каждой копии и был бы доступен всем, у кого есть доступ к базе.

Токен Яндекс Диска хранится в базе зашифрованным — см. core/secrets.py.
"""
import os
import shutil
import subprocess
import tempfile

from django.conf import settings

# Шифрование секретов в базе — общее для всего сайта.
from core.secrets import SECRET_PREFIX, decrypt_secret, encrypt_secret  # noqa: F401

ENCRYPTED_SUFFIX = '.gpg'


class EncryptionError(Exception):
    pass


# ---------- Архивы (GPG) ----------

def encryption_password():
    return settings.BACKUP_ENCRYPTION_PASSWORD or ''


def encryption_enabled():
    return bool(encryption_password())


def gpg_binary():
    return settings.BACKUP_GPG_BINARY or shutil.which('gpg') or 'gpg'


def _run_gpg(args, password):
    # Отдельная временная папка ключей: не зависим от домашней папки пользователя.
    with tempfile.TemporaryDirectory() as gnupg_home:
        env = os.environ.copy()
        env['GNUPGHOME'] = gnupg_home
        command = [gpg_binary(), '--batch', '--yes', '--no-tty', '--quiet',
                   '--pinentry-mode', 'loopback', '--passphrase-fd', '0', *args]
        try:
            result = subprocess.run(command, input=password, env=env, capture_output=True, text=True, timeout=3600)
        except FileNotFoundError:
            raise EncryptionError('Не найдена программа gpg. Установите GnuPG') from None
    return result


def encrypt_file(source, target, password=None):
    password = password or encryption_password()
    if not password:
        raise EncryptionError('Не задан пароль шифрования BACKUP_ENCRYPTION_PASSWORD')
    result = _run_gpg([
        '--symmetric',
        '--cipher-algo', 'AES256',
        '--s2k-mode', '3', '--s2k-digest-algo', 'SHA512', '--s2k-count', '65011712',
        # Архив уже сжат gzip — повторно не сжимаем.
        '--compress-algo', 'none',
        '--output', str(target),
        str(source),
    ], password)
    if result.returncode != 0:
        raise EncryptionError(f'Не удалось зашифровать копию: {result.stderr.strip()}')


def decrypt_file(source, target, password=None):
    password = password or encryption_password()
    if not password:
        raise EncryptionError(
            'Копия зашифрована. Укажите в .env пароль BACKUP_ENCRYPTION_PASSWORD, '
            'с которым она создавалась, и перезапустите контейнеры: docker compose up -d'
        )
    result = _run_gpg(['--decrypt', '--output', str(target), str(source)], password)
    if result.returncode != 0:
        if 'Bad session key' in result.stderr or 'decryption failed' in result.stderr:
            raise EncryptionError(
                'Неверный пароль шифрования. Копия создавалась с другим BACKUP_ENCRYPTION_PASSWORD'
            )
        raise EncryptionError(f'Не удалось расшифровать копию: {result.stderr.strip()}')
