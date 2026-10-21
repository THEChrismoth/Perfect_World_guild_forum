from .models import Notification
from .utils import get_unread_count

def notifications_context(request):
    if request.user.is_authenticated:
        unread_count = get_unread_count(request.user)
        notifications = Notification.objects.filter(user=request.user)[:10]
        return {
            'unread_notifications_count': unread_count,
            'notifications': notifications,
        }
    return {
        'unread_notifications_count': 0,
        'notifications': [],
    }