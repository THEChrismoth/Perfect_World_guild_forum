from django.core.management.base import BaseCommand

from auction.services import finish_expired_lots


class Command(BaseCommand):
    help = ('Завершает лоты, у которых закончилось время торгов. Обычно это делает планировщик '
            '(контейнер scheduler) сам — команда нужна для ручного запуска')

    def handle(self, *args, **options):
        finished, problems = finish_expired_lots()
        self.stdout.write(self.style.SUCCESS(f'Завершено лотов: {finished}'))
        if problems:
            self.stdout.write(self.style.WARNING(f'Не удалось завершить: {problems} — администраторы получили уведомление'))
