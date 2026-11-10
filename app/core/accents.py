"""Цвета оформления. Палитры — в static_src/admin/css/guild_theme.css и static_src/css/auth.css.

Цвет по умолчанию задаётся в настройках сайта; в профиле пустое значение означает «как у гильдии».
"""

ACCENT_CHOICES = [
    ('indigo', 'Индиго'),
    ('blue', 'Синий'),
    ('teal', 'Бирюзовый'),
    ('pink', 'Розовый'),
    ('orange', 'Оранжевый'),
]
ACCENT_NAMES = dict(ACCENT_CHOICES)
DEFAULT_ACCENT = 'indigo'

# Значение формы «Цвет гильдии» в меню выбора: в профиль записывается пустая строка.
GUILD_ACCENT = 'guild'


def guild_accent():
    from .models import SiteSettings

    return SiteSettings.load().accent_color or DEFAULT_ACCENT


def user_accent(user, guild=None):
    """Цвет, которым показывать сайт пользователю: свой из профиля или цвет гильдии."""
    profile = getattr(user, 'profile', None) if user.is_authenticated else None
    own = profile.accent_color if profile else ''
    return own if own in ACCENT_NAMES else (guild or guild_accent())
