from django.urls import path

from . import views

app_name = 'teamspeak'

urlpatterns = [
    path('access/', views.request_access, name='request_access'),
    path('confirm/<str:token>/', views.confirm, name='confirm'),
    path('rooms/create/', views.room_create, name='room_create'),
    path('rooms/<int:room_id>/delete/', views.room_delete, name='room_delete'),
]
