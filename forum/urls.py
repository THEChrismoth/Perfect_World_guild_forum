from django.urls import path
from . import views

urlpatterns = [
    path('', views.forum_view, name='home'),
    path('subcategory/<slug:slug>/', views.subcategory_detail, name='subcategory_detail'),
]
