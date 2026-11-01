from .accents import accent_menu
from .models import SiteSettings


def site_settings(request):
    settings = SiteSettings.load()
    menu = accent_menu(request.user, settings.accent_color)
    # Цвет оформления: свой из профиля или цвет гильдии (атрибут data-accent на <html>);
    # accent_menu — кружки выбора цвета в меню профиля.
    return {'site_settings': settings, 'site_accent': menu['accent'], 'accent_menu': menu}


def site_nav(request):
    """Боковое меню сайта. Функция, а не список: шаблон вызовет её, только если меню выводит
    (на страницах входа и в админ-панели оно не строится)."""
    if not request.user.is_authenticated:
        return {}

    def build():
        from notifications.utils import get_unread_count
        from .site_nav import build_site_nav

        return build_site_nav(request, get_unread_count(request.user))

    def online():
        from .site_nav import online_summary

        return online_summary()

    return {'site_nav': build, 'site_online': online}
