from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse
from .models import Notification
from .utils import mark_all_as_read


@login_required
def notification_list(request):
    """Страница всех уведомлений"""
    notifications = Notification.objects.filter(user=request.user)
    return render(request, 'notifications/notification_list.html', {
        'notifications': notifications,
    })


@login_required
def notification_detail(request, notification_id):
    """Детальный просмотр уведомления"""
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    notification.mark_as_read()

    if notification.link:
        return redirect(notification.link)
    return redirect('notifications:notification_list')


@login_required
def mark_as_read(request, notification_id):
    """Пометить уведомление как прочитанное"""
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    notification.mark_as_read()

    if request.GET.get('next'):
        return redirect(request.GET.get('next'))
    return redirect('notifications:notification_list')


@login_required
def mark_all_as_read_view(request):
    """Пометить все уведомления как прочитанные"""
    mark_all_as_read(request.user)
    messages.success(request, 'Все уведомления отмечены как прочитанные')

    # Возвращаемся на предыдущую страницу или на страницу уведомлений
    next_url = request.GET.get('next', '/')
    return redirect(next_url)


@login_required
def mark_all_as_read_from_dropdown(request):
    """Пометить все уведомления как прочитанные (из выпадающего списка)"""
    mark_all_as_read(request.user)
    # Возвращаемся на ту же страницу, где был открыт dropdown
    return redirect(request.META.get('HTTP_REFERER', '/'))


@login_required
def delete_notification(request, notification_id):
    """Удалить уведомление"""
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    notification.delete()
    messages.success(request, 'Уведомление удалено')
    return redirect('notifications:notification_list')