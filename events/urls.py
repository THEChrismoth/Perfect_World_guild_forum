from django.urls import path
from . import views

app_name = 'events'

urlpatterns = [
    path('', views.event_index, name='event_index'),
    path('<slug:event_type_slug>/', views.event_detail, name='event_detail'),
    path('vote/<int:notification_id>/', views.vote_view, name='vote_view'),
    path('vote/<int:notification_id>/results/', views.vote_results, name='vote_results'),
    path('my-votes/', views.my_votes, name='my_votes'),
]
