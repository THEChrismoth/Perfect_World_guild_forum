from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('forum.urls')),
    path('koslist/', include('koslist.urls')),
    path('profiles/', include('profiles.urls')),
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html',
                                                redirect_authenticated_user=True), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('auction/', include('auction.urls', namespace='auction')),
    path('reception/', include('reception.urls')),
    path('notifications/', include('notifications.urls')),
    path('events/', include('events.urls')),
    path('teamspeak/', include('teamspeak.urls')),
    # API для бота TeamSpeak (авторизация по TSBOT_API_TOKEN).
    path('api/tsbot/', include('teamspeak.api_urls')),
    # Вход в демо-роли. Без DEMO_MODE отвечает 404.
    path('demo/', include('demo.urls')),
# Загруженные файлы при разработке (на сервере их отдаёт Caddy). Без входа — там же иконка сайта для страницы входа.
] + static(settings.MEDIA_URL, login_not_required(serve), document_root=settings.MEDIA_ROOT)

