"""Шифрование текста переписки с проверкой принадлежности сообщения."""

import json
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.views.decorators.debug import sensitive_variables


class MessageCryptoError(Exception):
    """Ключ недоступен или сообщение не прошло проверку целостности."""


@sensitive_variables()
def cipher():
    """Собрать шифратор из независимых ключей переписки.

    Returns:
        MultiFernet с текущим ключом первым и прежними ключами для чтения.

    Raises:
        MessageCryptoError: Файл ключей недоступен или набор ключей некорректен.
    """
    keys = settings.PRIVATE_MESSAGES_KEYS
    if not keys:
        try:
            keys = Path(settings.PRIVATE_MESSAGES_KEY_FILE).read_text(encoding='ascii').splitlines()
        except (OSError, UnicodeError):
            raise MessageCryptoError('Ключ личных сообщений недоступен.') from None
    try:
        return MultiFernet([Fernet(key.strip().encode()) for key in keys if key.strip()])
    except (ValueError, TypeError):
        raise MessageCryptoError('Ключ личных сообщений некорректен.') from None


def configured():
    """Проверить доступность и формат ключей без расшифровки существующих сообщений."""
    try:
        cipher()
        return True
    except MessageCryptoError:
        return False


@sensitive_variables()
def encrypt(text, conversation_id, sender_id, client_id):
    """Зашифровать текст вместе с контекстом его принадлежности.

    Args:
        text: Открытый текст сообщения.
        conversation_id: ID диалога.
        sender_id: ID отправителя.
        client_id: UUID отправки.

    Returns:
        Строка Fernet для сохранения в базе.

    Raises:
        MessageCryptoError: Ключи переписки недоступны или некорректны.
    """
    payload = {
        'v': 1,
        'conversation': conversation_id,
        'sender': sender_id,
        'client': str(client_id),
        'text': text,
    }
    return cipher().encrypt(json.dumps(payload, ensure_ascii=False).encode()).decode('ascii')


@sensitive_variables()
def decrypt(token, conversation_id, sender_id, client_id):
    """Расшифровать сообщение и проверить его принадлежность переданному контексту.

    Args:
        token: Сохранённый шифротекст Fernet.
        conversation_id: Ожидаемый ID диалога.
        sender_id: Ожидаемый ID отправителя.
        client_id: Ожидаемый UUID отправки.

    Returns:
        Исходный текст сообщения.

    Raises:
        MessageCryptoError: Ключи недоступны, шифротекст повреждён или контекст чужой.
    """
    try:
        payload = json.loads(cipher().decrypt(token.encode('ascii')))
        if (
            not isinstance(payload, dict)
            or payload.get('v') != 1
            or payload.get('conversation') != conversation_id
            or payload.get('sender') != sender_id
            or payload.get('client') != str(client_id)
            or not isinstance(payload.get('text'), str)
        ):
            raise MessageCryptoError('Сообщение не прошло проверку целостности.')
        return payload['text']
    except (InvalidToken, UnicodeError, ValueError, TypeError):
        raise MessageCryptoError('Сообщение недоступно для расшифровки.') from None
