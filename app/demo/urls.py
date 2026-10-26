from django.urls import path

from . import views

app_name = 'demo'

urlpatterns = [
    path('login/<str:role>/', views.demo_login, name='login'),
]
