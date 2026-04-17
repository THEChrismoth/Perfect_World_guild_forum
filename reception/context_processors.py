from .models import ApplicationNotification

def notifications_context(request):
    if request.user.is_authenticated:
        unread_count = ApplicationNotification.objects.filter(user=request.user, is_read=False).count()
        notifications = ApplicationNotification.objects.filter(user=request.user)[:10]
        return {
            'unread_notifications_count': unread_count,
            'notifications': notifications,
        }
    return {
        'unread_notifications_count': 0,
        'notifications': [],
    }
