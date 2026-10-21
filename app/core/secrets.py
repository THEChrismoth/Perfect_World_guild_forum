"""Шифрование секретов, которые хранятся в базе (пароль почты, ключи капчи, токен Яндекс Диска).

Ключ получается из DJANGO_SECRET_KEY: утечка базы или резервной копии не раскрывает секреты.
Если SECRET_KEY сменить, сохранённые секреты перестанут расшифровываться — их нужно ввести заново.
"""
import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings

SECRET_PREFIX = 'fernet:'


def _fernet():
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        # Метка осталась от первой версии (токен Яндекса в backups) — менять нельзя,
        # иначе уже сохранённые секреты перестанут расшифровываться.
        info=b'backups.secret-field',
    ).derive(settings.SECRET_KEY.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(value):
    if not value:
        return ''
    if value.startswith(SECRET_PREFIX):
        return value
    return SECRET_PREFIX + _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value):
    """Возвращает расшифрованное значение.

    Если расшифровать не удалось (например, сменился SECRET_KEY), возвращает None.
    """
    if not value:
        return ''
    if not value.startswith(SECRET_PREFIX):
        # Значение, сохранённое до появления шифрования.
        return value
    try:
        return _fernet().decrypt(value[len(SECRET_PREFIX):].encode()).decode()
    except InvalidToken:
        return None
