from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from forum.models import Category, SubCategory
from notifications.models import Notification
from .models import AuctionLot, AuctionBid, PointsTransaction


@override_settings(SECURE_SSL_REDIRECT=False)
class AuctionTestCase(TestCase):
    def setUp(self):
        category = Category.objects.create(title='Гильдия', slug='guild')
        SubCategory.objects.create(title='Аукцион', slug='auction', category=category, is_auction=True)

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
    def test_two_auction_subcategories_do_not_close_auction(self):
        category = Category.objects.get(slug='guild')
        SubCategory.objects.create(title='Аукцион 2', slug='auction-2', category=category, is_auction=True)
        self.client.force_login(self.alice)

        response = self.client.get(reverse('auction:auction_index'))
        self.assertEqual(response.status_code, 200)
