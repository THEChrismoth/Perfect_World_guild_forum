from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('forum/<int:forum_id>/', views.forum_detail, name='forum_detail'),
    path('topic/<int:topic_id>/', views.topic_detail, name='topic_detail'),
    path('topic/create/<int:forum_id>/', views.create_topic, name='create_topic'),
    path('post/create/<int:topic_id>/', views.create_post, name='create_post'),
]
