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
            lot.process_auction_end()
            self.stdout.write(
                self.style.SUCCESS(f'Обработан аукцион: {lot.name}')
            )
            count += 1
        
        self.stdout.write(
            self.style.SUCCESS(f'Обработано {count} аукционов')
        )
