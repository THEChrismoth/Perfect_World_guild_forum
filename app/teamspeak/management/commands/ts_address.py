from django.core.management.base import BaseCommand

from teamspeak.models import TeamSpeakSettings


class Command(BaseCommand):
    help = 'Показывает или задает адрес сервера TeamSpeak, который видят игроки (Настройки TeamSpeak)'

    def add_arguments(self, parser):
        parser.add_argument('address', nargs='?', help='Новый адрес, например ts.myguild.ru')

    def handle(self, *args, address=None, **options):
        ts_settings = TeamSpeakSettings.load()
        if address is not None:
            ts_settings.server_address = address.strip()
            ts_settings.save(update_fields=['server_address'])
        self.stdout.write(ts_settings.display_address())
