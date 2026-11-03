from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.roles import GUILD_GROUP
from notifications.models import Notification
from .models import AuctionLot, AuctionBid, PointsTransaction


@override_settings(SECURE_SSL_REDIRECT=False)
class AuctionTestCase(TestCase):
    def setUp(self):
        # Аукцион открыт только членам гильдии.
        self.guild = Group.objects.create(name=GUILD_GROUP)
        self.alice = self.make_user('alice', 100)
        self.bob = self.make_user('bob', 100)
        self.lot = AuctionLot.objects.create(
            name='Камень мироздания',
            initial_price=10,
            min_step=5,
            end_date=timezone.now() + timedelta(hours=1),
        )

    def make_user(self, username, points):
        user = User.objects.create_user(username, password='pass')
        user.groups.add(self.guild)
        user.profile.activity_points = points
        user.profile.save()
        return user

    def bid(self, user, amount):
        self.client.force_login(user)
        return self.client.post(reverse('auction:lot_detail', args=[self.lot.slug]), {'bid_amount': amount})

    def expire_lot(self):
        AuctionLot.objects.filter(pk=self.lot.pk).update(end_date=timezone.now() - timedelta(seconds=1))
        self.lot.refresh_from_db()

    def finish_lot(self, **kwargs):
        self.expire_lot()
        success, _ = self.lot.process_auction_end(**kwargs)
        return success


class BidTests(AuctionTestCase):
    def test_bid_freezes_points(self):
        self.bid(self.alice, 15)

        self.lot.refresh_from_db()
        self.assertEqual(self.lot.current_price, 15)
        self.assertEqual(self.alice.profile.get_available_points(), 85)
        self.assertTrue(PointsTransaction.objects.filter(user=self.alice, transaction_type='freeze', amount=15).exists())

    def test_bid_below_minimum_rejected(self):
        self.bid(self.alice, 14)

        self.lot.refresh_from_db()
        self.assertEqual(self.lot.current_price, 10)
        self.assertFalse(AuctionBid.objects.exists())

    def test_not_enough_points_rejected(self):
        self.bid(self.alice, 150)

        self.assertFalse(AuctionBid.objects.exists())

    def test_leader_cannot_bid_again(self):
        self.bid(self.alice, 15)
        self.bid(self.alice, 30)

        self.assertEqual(AuctionBid.objects.filter(bidder=self.alice).count(), 1)

    def test_outbid_unfreezes_previous_leader(self):
        self.bid(self.alice, 15)
        self.bid(self.bob, 20)

        alice_bid = AuctionBid.objects.get(bidder=self.alice)
        self.assertFalse(alice_bid.is_frozen)
        self.assertEqual(alice_bid.status, 'outbid')
        self.assertEqual(self.alice.profile.get_available_points(), 100)
        self.assertEqual(self.bob.profile.get_available_points(), 80)
        self.assertEqual(self.lot.bids.get(is_frozen=True).bidder, self.bob)

    def test_bid_after_planned_end_rejected(self):
        self.expire_lot()
        self.bid(self.alice, 15)

        self.assertFalse(AuctionBid.objects.exists())
        # До решения администратора лот остается активным.
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.status, 'active')

    def test_bid_on_ended_lot_rejected(self):
        self.finish_lot()
        self.bid(self.alice, 15)

        self.assertFalse(AuctionBid.objects.exists())

    def test_my_bids_page(self):
        self.bid(self.alice, 15)
        response = self.client.get(reverse('auction:my_bids'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.lot.name)


class AuctionEndTests(AuctionTestCase):
    def test_winner_pays_and_gets_notified(self):
        admin = User.objects.create_superuser('admin', password='pass')
        self.bid(self.alice, 15)
        self.bid(self.bob, 20)

        self.assertTrue(self.finish_lot(ended_by_user=admin))

        self.lot.refresh_from_db()
        self.assertEqual(self.lot.status, 'ended')
        self.assertEqual(self.lot.ended_by, admin)
        self.assertIsNotNone(self.lot.ended_at)
        winner = self.lot.bids.get(is_winner=True)
        self.assertEqual(winner.bidder, self.bob)
        self.assertEqual(winner.status, 'won')
        self.bob.profile.refresh_from_db()
        self.assertEqual(self.bob.profile.activity_points, 80)
        self.assertEqual(self.bob.profile.spent_points, 20)
        self.alice.profile.refresh_from_db()
        self.assertEqual(self.alice.profile.activity_points, 100)
        self.assertTrue(Notification.objects.filter(user=self.bob, notification_type='auction_win').exists())

    def test_end_is_processed_once(self):
        self.bid(self.alice, 15)
        self.assertTrue(self.finish_lot())
        success, _ = self.lot.process_auction_end()
        self.assertFalse(success)

        self.alice.profile.refresh_from_db()
        self.assertEqual(self.alice.profile.activity_points, 85)

    def test_winner_without_points_rolls_back(self):
        self.bid(self.alice, 50)
        # Админ уменьшил баланс уже после ставки.
        self.alice.profile.refresh_from_db()
        self.alice.profile.activity_points = 10
        self.alice.profile.save()

        self.assertFalse(self.finish_lot())

        # Ничего не изменилось: админ может выбрать другого победителя.
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.status, 'active')
        bid = AuctionBid.objects.get(bidder=self.alice)
        self.assertFalse(bid.is_winner)
        self.assertTrue(bid.is_frozen)
        self.alice.profile.refresh_from_db()
        self.assertEqual(self.alice.profile.activity_points, 10)
        self.assertFalse(PointsTransaction.objects.filter(transaction_type='debit').exists())

    def test_admin_chooses_winner(self):
        self.bid(self.alice, 15)
        self.bid(self.bob, 20)

        self.assertTrue(self.finish_lot(force_winner_id=self.alice.id))

        winner = self.lot.bids.get(is_winner=True)
        self.assertEqual(winner.bidder, self.alice)
        self.alice.profile.refresh_from_db()
        self.assertEqual(self.alice.profile.activity_points, 85)
        self.bob.profile.refresh_from_db()
        self.assertEqual(self.bob.profile.activity_points, 100)

    def test_cancel_returns_points(self):
        self.bid(self.alice, 15)

        success, _ = self.lot.cancel_auction()

        self.assertTrue(success)
        self.assertEqual(self.lot.status, 'cancelled')
        self.assertEqual(self.alice.profile.get_available_points(), 100)

    def test_lot_without_bids_ends(self):
        self.assertTrue(self.finish_lot())
        self.assertEqual(self.lot.status, 'ended')


class AuctionAccessTests(AuctionTestCase):
    def test_only_guild_members(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse('auction:auction_index')).status_code, 200)

        outsider = User.objects.create_user('outsider', password='pass')
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(reverse('auction:auction_index')).status_code, 403)
        self.assertEqual(self.client.get(reverse('auction:lot_detail', args=[self.lot.slug])).status_code, 403)


class LotAdminTests(AuctionTestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser('boss', 'boss@example.com', 'pass')
        self.client.force_login(self.admin)

    def test_create_lot_with_single_datetime_fields(self):
        response = self.client.post(reverse('admin:auction_auctionlot_add'), {
            'name': 'Опал', 'description': '', 'initial_price': 10, 'min_step': 5,
            'start_date': '2026-11-03T12:00', 'end_date': '2099-11-06T12:00',
        })

        self.assertEqual(response.status_code, 302)
        lot = AuctionLot.objects.get(name='Опал')
        self.assertEqual(timezone.localtime(lot.end_date).strftime('%Y-%m-%d %H:%M'), '2099-11-06 12:00')

    def test_end_date_required(self):
        response = self.client.post(reverse('admin:auction_auctionlot_add'), {
            'name': 'Опал', 'description': '', 'initial_price': 10, 'min_step': 5,
            'start_date': '2026-11-03T12:00', 'end_date': '',
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(AuctionLot.objects.filter(name='Опал').exists())

    def test_bids_table_only_when_there_are_bids(self):
        add = self.client.get(reverse('admin:auction_auctionlot_add'))
        change = self.client.get(reverse('admin:auction_auctionlot_change', args=[self.lot.pk]))
        self.assertNotContains(add, 'bids-group')
        self.assertNotContains(change, 'bids-group')

        self.bid(self.alice, 15)
        self.client.force_login(self.admin)
        change = self.client.get(reverse('admin:auction_auctionlot_change', args=[self.lot.pk]))
        self.assertContains(change, 'bids-group')

    def test_preview_shows_unsaved_values_and_image(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        image = SimpleUploadedFile('lot.png', b'\x89PNG\r\n\x1a\n', content_type='image/png')
        response = self.client.post(reverse('admin:auction_lot_preview'), {
            'name': 'Пряжа времени', 'initial_price': '25', 'min_step': '5', 'end_date': '', 'image': image,
        })

        self.assertContains(response, 'Пряжа времени')
        self.assertContains(response, 'data:image/png;base64,')
        self.assertContains(response, 'без срока')
        self.assertFalse(AuctionLot.objects.filter(name='Пряжа времени').exists())


class BiddingFlowTests(AuctionTestCase):
    def test_outbid_player_is_notified(self):
        self.bid(self.alice, 15)
        self.bid(self.bob, 20)

        notification = Notification.objects.get(user=self.alice, title='⚠️ Вашу ставку перебили')
        self.assertIn('15 ⭐', notification.message)
        self.assertIn('20 ⭐', notification.message)
        self.assertFalse(Notification.objects.filter(user=self.bob, title='⚠️ Вашу ставку перебили').exists())

    def test_late_bid_extends_auction(self):
        AuctionLot.objects.filter(pk=self.lot.pk).update(end_date=timezone.now() + timedelta(minutes=2))

        self.bid(self.alice, 15)

        self.lot.refresh_from_db()
        self.assertGreater(self.lot.end_date, timezone.now() + timedelta(minutes=4))

    def test_extension_capped_at_30_minutes(self):
        planned_end = timezone.now() + timedelta(minutes=2)
        AuctionLot.objects.filter(pk=self.lot.pk).update(end_date=planned_end)
        carol = self.make_user('carol', 100)

        # Торги уже продлевали почти до предела: следующая ставка дотягивает только до него.
        AuctionLot.objects.filter(pk=self.lot.pk).update(
            original_end_date=planned_end - timedelta(minutes=28), end_date=planned_end)
        self.bid(self.alice, 15)
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.end_date, planned_end + timedelta(minutes=2))

        # Предел достигнут — новая ставка торги больше не продлевает.
        self.bid(carol, 20)
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.end_date, planned_end + timedelta(minutes=2))

    def test_admin_new_end_date_resets_limit(self):
        admin = User.objects.create_superuser('boss', 'boss@example.com', 'pass')
        AuctionLot.objects.filter(pk=self.lot.pk).update(original_end_date=timezone.now())
        self.client.force_login(admin)

        self.client.post(reverse('admin:auction_auctionlot_change', args=[self.lot.pk]), {
            'name': self.lot.name, 'description': '', 'initial_price': 10, 'min_step': 5,
            'start_date': '2026-11-01T12:00', 'end_date': '2099-01-01T12:00', 'status': 'active',
        })

        self.lot.refresh_from_db()
        self.assertEqual(self.lot.end_date.year, 2099)
        self.assertIsNone(self.lot.original_end_date)

    def test_early_bid_keeps_end_date(self):
        end_date = self.lot.end_date

        self.bid(self.alice, 15)

        self.lot.refresh_from_db()
        self.assertEqual(self.lot.end_date, end_date)


class AutoFinishTests(AuctionTestCase):
    def test_expired_lot_finishes_itself(self):
        from .services import finish_expired_lots

        self.bid(self.alice, 15)
        self.bid(self.bob, 20)
        self.expire_lot()

        self.assertEqual(finish_expired_lots(), (1, 0))

        self.lot.refresh_from_db()
        self.assertEqual(self.lot.status, 'ended')
        self.assertEqual(self.lot.bids.get(is_winner=True).bidder, self.bob)
        self.bob.profile.refresh_from_db()
        self.assertEqual(self.bob.profile.activity_points, 80)

    def test_payment_problem_notifies_admins_once(self):
        from .services import PAYMENT_PROBLEM_TITLE, finish_expired_lots

        admin = User.objects.create_superuser('admin', password='pass')
        self.bid(self.alice, 50)
        self.alice.profile.refresh_from_db()
        self.alice.profile.activity_points = 10
        self.alice.profile.save()
        self.expire_lot()

        self.assertEqual(finish_expired_lots(), (0, 1))
        finish_expired_lots()

        self.assertEqual(Notification.objects.filter(user=admin, title=PAYMENT_PROBLEM_TITLE).count(), 1)
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.status, 'active')

    def test_active_lot_untouched(self):
        from .services import finish_expired_lots

        self.bid(self.alice, 15)

        self.assertEqual(finish_expired_lots(), (0, 0))
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.status, 'active')
