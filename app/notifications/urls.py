from django.urls import path
from . import views

app_name = 'notifications'

urlpatterns = [
    path('', views.notification_list, name='notification_list'),
    path('<int:notification_id>/', views.notification_detail, name='notification_detail'),
    path('<int:notification_id>/read/', views.mark_as_read, name='mark_as_read'),
    path('read-all/', views.mark_all_as_read_view, name='mark_all_as_read'),
    path('read-all-dropdown/', views.mark_all_as_read_from_dropdown, name='mark_all_as_read_dropdown'),
    path('<int:notification_id>/delete/', views.delete_notification, name='delete_notification'),
]