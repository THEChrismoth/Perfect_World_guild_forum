from django.urls import reverse
from django.utils import timezone

from notifications.models import Notification
from notifications.utils import send_notification_to_admins
from .models import AuctionLot

PAYMENT_PROBLEM_TITLE = '⚠️ Аукцион не завершился сам'


def finish_expired_lots(now=None):
    """Завершает лоты, у которых закончилось время торгов: лидер платит, остальным очки возвращаются.

    Вызывается планировщиком (контейнер scheduler) раз в полминуты и командой check_auctions.
    Если списать очки у лидера не получилось (администратор уменьшил ему баланс), лот остаётся
    активным, а администраторы один раз получают уведомление — победителя выбирают вручную.
    Возвращает (завершено, с проблемой).
    """
    now = now or timezone.now()
    finished, problems = 0, 0
    for lot in AuctionLot.objects.filter(status='active', end_date__lte=now):
        success, message = lot.process_auction_end()
        if success:
            finished += 1
            continue
        problems += 1
        link = reverse('admin:auction_auctionlot_change', args=[lot.pk])
        if not Notification.objects.filter(title=PAYMENT_PROBLEM_TITLE, link=link).exists():
            send_notification_to_admins(
                title=PAYMENT_PROBLEM_TITLE,
                message=f'Лот «{lot.name}»: {message}. Завершите его вручную кнопкой «Завершить аукцион».',
                notification_type='auction',
                link=link,
                perm='auction.change_auctionlot',
            )
    return finished, problems
