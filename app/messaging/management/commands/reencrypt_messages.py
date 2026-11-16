from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from messaging.crypto import MessageCryptoError, decrypt, encrypt
from messaging.models import Message


class Command(BaseCommand):
    help = (
        'Перешифровывает сообщения первым ключом из набора; старые ключи пока должны быть доступны'
    )

    def handle(self, *args, **options):
        total = 0
        for pk in (
            Message.objects.order_by('pk').values_list('pk', flat=True).iterator(chunk_size=100)
        ):
            try:
                with transaction.atomic():
                    message = Message.objects.select_for_update().get(pk=pk)
                    text = decrypt(
                        message.ciphertext,
                        message.conversation_id,
                        message.sender_id,
                        message.client_id,
                    )
                    message.ciphertext = encrypt(
                        text, message.conversation_id, message.sender_id, message.client_id
                    )
                    message.save(update_fields=['ciphertext'])
                    total += 1
            except MessageCryptoError:
                raise CommandError(
                    f'Сообщение #{pk} не удалось перешифровать. Старые ключи нужно сохранить.'
                ) from None
        self.stdout.write(f'Перешифровано сообщений: {total}')
