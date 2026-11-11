import re
from html import unescape
from datetime import timedelta
from django.utils.html import strip_tags
from django.utils import timezone
from events.models import EventNotification, EventAttendance


def prepare_notifications(notifications, user):
    """Load event details and responses in bulk for notification cards."""
    notifications = list(notifications)
    ids = {}
    for item in notifications:
        # The stored HTML ends with a generated action link. Render that action
        # separately rather than including its label in the message preview.
        message = re.sub(
            r'<a\b[^>]*\bclass=["\']btn-vote-notify["\'][^>]*>.*?</a>',
            '', item.message, flags=re.IGNORECASE | re.DOTALL,
        )
        message = re.sub(r'<br\s*/?>', '\n', message, flags=re.IGNORECASE)
        item.card_message = unescape(strip_tags(message)).strip()
        match = re.fullmatch(r"/events/vote/(\d+)/", item.link or "")
        if match:
            ids[item.pk] = int(match[1])
    if not ids:
        return notifications
    events = EventNotification.objects.select_related("event_type").in_bulk(ids.values())
    votes = {vote.notification_id: vote for vote in EventAttendance.objects.filter(user=user, notification_id__in=events)}
    today = timezone.localdate()
    for item in notifications:
        event = events.get(ids.get(item.pk))
        if event:
            item.card_event = event
            vote = votes.get(event.pk)
            item.card_vote = vote.status if vote else ""
            item.card_comment = vote.comment if vote else ""
            day = event.event_date
            label = "Сегодня" if day == today else "Завтра" if day == today + timedelta(days=1) else day.strftime("%d.%m.%Y")
            item.card_schedule = label + (event.start_time.strftime(" в %H:%M") if event.start_time else "")
    return notifications
