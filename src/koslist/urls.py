from django.urls import path
from . import views

urlpatterns = [
    path('', views.kos_view, name='koslist'),
]

