from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from core.models import SiteSettings
from .models import Skirmish


class ModelTests(TestCase):
    def test_database_allows_only_one_active_skirmish(self):
        first = Skirmish.objects.create(title='Первый', code='0001', ts_channel='Гильдия')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Skirmish.objects.create(title='Второй', code='0002', ts_channel='Гильдия')
        first.ended_at = timezone.now()
        first.save()
        Skirmish.objects.create(title='Второй', code='0002', ts_channel='Гильдия')
        self.assertEqual(Skirmish.objects.filter(ended_at__isnull=True).count(), 1)

    def test_invalid_end_and_premature_review_are_rejected(self):
        start = timezone.now()
        for values in [{'ended_at': start - timedelta(seconds=1)}, {'reviewed_at': start}]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                Skirmish.objects.create(title='Сбор', code='0010', ts_channel='Гильдия',
                                         started_at=start, **values)

    def test_settings_do_not_change_existing_channel_snapshot(self):
        config = SiteSettings.load()
        config.skirmish_ts_channel = 'Гильдия / Сбор'
        config.save()
        session = Skirmish.objects.create(title='Сбор', code='0010', ts_channel=config.skirmish_ts_channel)
        config.skirmish_ts_channel = 'Гильдия / Другой'
        config.save()
        session.refresh_from_db()
        self.assertEqual(session.ts_channel, 'Гильдия / Сбор')
