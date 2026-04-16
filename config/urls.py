from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.shortcuts import render
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('forum.urls')),
    path('koslist/', include('koslist.urls')),
    path('profiles/', include('profiles.urls')),
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('captcha/', include('captcha.urls')),
    path('auction/', include('auction.urls', namespace='auction')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

