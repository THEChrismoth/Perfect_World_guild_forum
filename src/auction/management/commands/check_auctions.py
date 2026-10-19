from django.core.management.base import BaseCommand
from django.utils import timezone
from auction.models import AuctionLot

class Command(BaseCommand):
    help = 'Проверяет завершенные аукционы и обрабатывает их'

    def handle(self, *args, **options):
        ended_lots = AuctionLot.objects.filter(
            status='active',
            end_date__lte=timezone.now()
        )

        count = 0
        for lot in ended_lots:
            success, message = lot.process_auction_end()
            if success:
                self.stdout.write(
                    self.style.SUCCESS(f'Обработан аукцион: {lot.name}')
                )
                count += 1
            else:
                self.stdout.write(
                    self.style.WARNING(f'Аукцион {lot.name} не завершен: {message}')
                )

        self.stdout.write(
            self.style.SUCCESS(f'Обработано {count} аукционов')
        )
