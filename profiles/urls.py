from django.urls import path
from . import views

urlpatterns = [
    path('register/', views.register, name='register'),
    path('edit/', views.profile_edit, name='profile_edit'),
    path('<str:username>/', views.profile_view, name='profile_view'),
]
