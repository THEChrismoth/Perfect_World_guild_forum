"""Шифрование резервных копий и секретов.

Архивы шифруются стандартным GPG (OpenPGP, AES-256, ключ из пароля). Поэтому копию можно
расшифровать и без этого сайта: `gpg -d backup-....tar.gz.gpg > backup.tar.gz`
(в Windows — программой Gpg4win).

Пароль шифрования задается в .env (BACKUP_ENCRYPTION_PASSWORD) и намеренно не хранится в базе:
иначе он попадал бы внутрь каждой копии и был бы доступен всем, у кого есть доступ к базе.

Токен Яндекс Диска хранится в базе зашифрованным ключом, производным от SECRET_KEY:
утечка базы или копии не раскрывает токен.
"""
import base64
import os
import shutil
import subprocess
import tempfile

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings

ENCRYPTED_SUFFIX = '.gpg'
SECRET_PREFIX = 'fernet:'


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
    # Отдельная временная папка ключей: не зависим от домашней папки пользователя
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
        # Архив уже сжат gzip — повторно не сжимаем
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


# ---------- Секреты в базе (Fernet) ----------

def _fernet():
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b'backups.secret-field',
    ).derive(settings.SECRET_KEY.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(value):
    if not value:
        return ''
    return SECRET_PREFIX + _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value):
    """Возвращает расшифрованное значение или None, если расшифровать не удалось
    (например, сменился SECRET_KEY)"""
    if not value:
        return ''
    if not value.startswith(SECRET_PREFIX):
        # Значение, сохраненное до появления шифрования
        return value
    try:
        return _fernet().decrypt(value[len(SECRET_PREFIX):].encode()).decode()
    except InvalidToken:
        return None
