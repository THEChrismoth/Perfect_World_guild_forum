from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from .models import Notification
from .presentation import prepare_notifications
from .utils import mark_all_as_read


def safe_redirect(request, url, fallback='notifications:notification_list'):
    """Перенаправить только на разрешённый адрес сайта или запасной маршрут."""
    if url and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(url)
    return redirect(fallback)


@login_required
def notification_list(request):
    """Показать полный список уведомлений пользователя."""
    notifications = prepare_notifications(
        Notification.objects.filter(user=request.user), request.user
    )
    return render(
        request,
        'notifications/notification_list.html',
        {
            'notifications': notifications,
        },
    )


@login_required
def notification_detail(request, notification_id):
    """Отметить уведомление прочитанным и перейти по его безопасной ссылке."""
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    notification.mark_as_read()

    return safe_redirect(request, notification.link)


@login_required
def mark_as_read(request, notification_id):
    """Пометить уведомление как прочитанное."""
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    notification.mark_as_read()

    return safe_redirect(request, request.GET.get('next'))


@login_required
@require_POST
def mark_all_as_read_view(request):
    """Пометить все уведомления как прочитанные."""
    mark_all_as_read(request.user)
    messages.success(request, 'Все уведомления отмечены как прочитанные')

    # Возвращаемся на предыдущую страницу или на страницу уведомлений.
    return safe_redirect(request, request.POST.get('next'))


@login_required
@require_POST
def mark_all_as_read_from_dropdown(request):
    """Пометить все уведомления как прочитанные (из выпадающего списка)."""
    mark_all_as_read(request.user)
    # Возвращаемся на ту же страницу, где был открыт dropdown.
    return safe_redirect(request, request.META.get('HTTP_REFERER'), fallback='/')


@login_required
@require_POST
def delete_notification(request, notification_id):
    """Удалить уведомление."""
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    notification.delete()
    messages.success(request, 'Уведомление удалено')
    return redirect('notifications:notification_list')


@login_required
@require_POST
def delete_all_notifications(request):
    """Удалить все уведомления только текущего пользователя."""
    Notification.objects.filter(user=request.user).delete()
    messages.success(request, 'Все уведомления удалены')
    return safe_redirect(request, request.POST.get('next'))
