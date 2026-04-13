from django.urls import path
from . import views

urlpatterns = [
    path('', views.forum_view, name='home'),
    path('subcategory/<slug:slug>/', views.subcategory_detail, name='subcategory_detail'),
    path('subcategory/<slug:slug>/create/', views.topic_create, name='topic_create'),
    path('topic/<slug:slug>/', views.topic_detail, name='topic_detail'),
    path('topic/<slug:slug>/delete/', views.topic_delete, name='topic_delete'),
    path('topic/<slug:slug>/reply/', views.post_create, name='post_create'),
]
