from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class PermanentRosterMigrationTests(TransactionTestCase):
    def test_legacy_rosters_and_invitations_are_preserved(self):
        before = [('events', '0006_fill_empty_slugs')]
        after = [('events', '0008_dated_invitations')]
        executor = MigrationExecutor(connection)
        executor.migrate(before)
        try:
            old = executor.loader.project_state(before).apps
            Type = old.get_model('events', 'EventType')
            Event = old.get_model('events', 'Event')
            Party = old.get_model('events', 'Party')
            Member = old.get_model('events', 'PartyMember')
            Invitation = old.get_model('events', 'EventNotification')
            User = old.get_model('auth', 'User')
            user = User.objects.create(username='migration-player')
            kind = Type.objects.create(name='Legacy', slug='legacy')
            missing = Type.objects.create(name='Missing', slug='missing', parties_count=2)
            first = Event.objects.create(event_type=kind, notes='First')
            second = Event.objects.create(event_type=kind, notes='Second')
            Party.objects.create(event=first, number=1, leader=user)
            party = Party.objects.create(event=second, number=1)
            Member.objects.create(party=party, user=user)
            draft = Invitation.objects.create(event_type=kind, event_date=date(2030, 1, 1), subject='Draft', message='')
            sent = Invitation.objects.create(event_type=kind, event_date=date(2030, 1, 2), subject='Sent', message='')
            sent.sent_to_users.add(user)
            Invitation.objects.filter(pk=sent.pk).update(sent_at=timezone.now())
            executor = MigrationExecutor(connection)
            executor.migrate(after)
            new = executor.loader.project_state(after).apps
            NewEvent = new.get_model('events', 'Event')
            NewParty = new.get_model('events', 'Party')
            NewMember = new.get_model('events', 'PartyMember')
            NewInvitation = new.get_model('events', 'EventNotification')
            roster = NewEvent.objects.get(event_type_id=kind.pk)
            self.assertIn('First', roster.notes)
            self.assertIn('Second', roster.notes)
            self.assertEqual(list(NewParty.objects.filter(event=roster).order_by('number').values_list('number', flat=True)), [1, 2])
            self.assertTrue(NewParty.objects.filter(event=roster, leader_id=user.pk).exists())
            self.assertTrue(NewMember.objects.filter(party__event=roster, user_id=user.pk).exists())
            self.assertEqual(NewParty.objects.filter(event__event_type_id=missing.pk).count(), 2)
            self.assertIsNone(NewInvitation.objects.get(pk=draft.pk).sent_at)
            self.assertIsNotNone(NewInvitation.objects.get(pk=sent.pk).sent_at)
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
