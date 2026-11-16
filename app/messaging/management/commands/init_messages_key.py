import os
from pathlib import Path

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from messaging.crypto import MessageCryptoError, cipher


class Command(BaseCommand):
    help = 'Создаёт отдельный ключ переписки без вывода секрета и без замены существующего ключа'

    def handle(self, *args, **options):
        target = Path(settings.PRIVATE_MESSAGES_KEY_FILE)
        if not settings.PRIVATE_MESSAGES_KEYS and not target.exists():
            from messaging.models import Message

            if Message.objects.exists():
                raise CommandError(
                    'В базе уже есть переписка. Восстановите её прежний ключ; новый не создаётся.'
                )
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            try:
                descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(descriptor, 'wb') as output:
                    output.write(Fernet.generate_key() + b'\n')
                self.stdout.write(
                    'Создан отдельный ключ личных сообщений. Сохраните его отдельно от базы данных.'
                )
        try:
            cipher()
        except MessageCryptoError as error:
            raise CommandError(str(error)) from None
