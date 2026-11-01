from .accents import user_accent
from .models import SiteSettings


def site_settings(request):
    settings = SiteSettings.load()
    # Цвет оформления: свой из профиля или цвет гильдии (атрибут data-accent на <html>).
    return {'site_settings': settings, 'site_accent': user_accent(request.user, settings.accent_color)}


def site_nav(request):
    """Боковое меню сайта. Функция, а не список: шаблон вызовет её, только если меню выводит
    (на страницах входа и в админ-панели оно не строится)."""
    if not request.user.is_authenticated:
        return {}

    def build():
        from notifications.utils import get_unread_count
        from .site_nav import build_site_nav

        return build_site_nav(request, get_unread_count(request.user))

    return {'site_nav': build}
