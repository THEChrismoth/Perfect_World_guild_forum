from django.urls import path

from . import views

app_name = 'demo'

urlpatterns = [
    path('login/<str:role>/', views.demo_login, name='login'),
    path('teamspeak/', views.teamspeak_preview, name='teamspeak'),
    path('teamspeak/action/', views.teamspeak_action, name='teamspeak_action'),
    path('skirmish-presence/', views.skirmish_presence, name='skirmish_presence'),
]
