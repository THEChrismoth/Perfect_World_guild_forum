from django.test import SimpleTestCase
from django.urls import resolve

from . import views


class EventUrlTests(SimpleTestCase):
    def test_my_votes_not_taken_as_event_slug(self):
        self.assertEqual(resolve('/events/my-votes/').func, views.my_votes)

    def test_event_slug_still_works(self):
        self.assertEqual(resolve('/events/some-event/').func, views.event_detail)
