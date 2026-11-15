from django.urls import path

from . import views

app_name = 'messaging'
urlpatterns = [
    path('', views.inbox, name='inbox'),
    path('contacts/', views.contacts, name='contacts'),
    path('badge/', views.badge, name='badge'),
    path('to/<int:user_id>/', views.compose, name='compose'),
    path('<int:pk>/', views.conversation, name='conversation'),
    path('<int:pk>/send/', views.send, name='send'),
    path('<int:pk>/block/', views.block, name='block'),
    path('<int:pk>/updates/', views.updates, name='updates'),
    path('<int:pk>/read/', views.read, name='read'),
]
