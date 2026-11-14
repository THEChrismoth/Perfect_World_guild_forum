from django.urls import path

from . import views

app_name = 'skirmishes'
urlpatterns = [
    path('', views.index, name='index'),
    path('start/', views.start, name='start'),
    path('join/', views.join, name='join'),
    path('<int:pk>/', views.detail, name='detail'),
    path('<int:pk>/finish/', views.finish, name='finish'),
    path('<int:pk>/confirm/', views.confirm, name='confirm'),
    path('<int:pk>/correct/', views.correct, name='correct'),
]
