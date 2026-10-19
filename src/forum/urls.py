from django.urls import path
from . import views

urlpatterns = [
    path('', views.forum_view, name='index'),
    path('subcategory/<slug:slug>/', views.subcategory_detail, name='subcategory_detail'),
    path('topic/create/<slug:slug>/', views.topic_create, name='topic_create'),
    path('topic/<slug:slug>/', views.topic_detail, name='topic_detail'),
    path('topic/<slug:slug>/edit/', views.topic_edit, name='topic_edit'),
    path('topic/<slug:slug>/delete/', views.topic_delete, name='topic_delete'),
    path('post/create/<slug:slug>/', views.post_create, name='post_create'),
    path('post/<int:post_id>/edit/', views.post_edit, name='post_edit'),
    path('post/<int:post_id>/delete/', views.post_delete, name='post_delete'),
]
