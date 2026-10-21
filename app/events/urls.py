from django.urls import path
from . import views

app_name = 'events'

urlpatterns = [
    path('', views.event_index, name='event_index'),
    # Фиксированные адреса должны идти до <slug>, иначе my-votes/ примется за slug ивента.
    path('my-votes/', views.my_votes, name='my_votes'),
    path('vote/<int:notification_id>/', views.vote_view, name='vote_view'),
    path('vote/<int:notification_id>/results/', views.vote_results, name='vote_results'),
    path('<slug:event_type_slug>/', views.event_detail, name='event_detail'),
]
