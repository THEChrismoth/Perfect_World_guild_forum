from .accents import user_accent
from .models import SiteSettings


def site_settings(request):
    settings = SiteSettings.load()
    # Цвет оформления: свой из профиля или цвет гильдии (атрибут data-accent на <html>).
    return {'site_settings': settings, 'site_accent': user_accent(request.user, settings.accent_color)}
