"""Админ-панель сайта: свой порядок и иконки разделов, боковое меню, название из настроек и дашборд на главной.

Подключается через core.apps.GuildAdminConfig вместо django.contrib.admin, поэтому все
@admin.register и admin.site в проекте работают с этим классом без изменений.
"""
from django.contrib import admin
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

# Порядок разделов в меню: сначала повседневные дела гильдии, в конце — служебное.
# Иконки — имена из core/templatetags/ga_admin.py.
APP_ORDER = [
    ('reception', 'file-text'),
    ('profiles', 'table'),
    ('events', 'swords'),
    ('auction', 'gavel'),
    ('koslist', 'skull'),
    ('forum', 'message'),
    ('notifications', 'bell'),
    ('teamspeak', 'headphones'),
    ('auth', 'users'),
    ('core', 'settings'),
    ('backups', 'database'),
]
APP_POSITION = {label: index for index, (label, _) in enumerate(APP_ORDER)}
APP_ICON = dict(APP_ORDER)

# Группы бокового меню. Разделы, которых здесь нет, попадают в «Прочее».
NAV_GROUPS = [
    ('Гильдия', ('reception', 'profiles', 'events', 'auction', 'koslist')),
    ('Сообщество', ('forum', 'notifications', 'teamspeak')),
    ('Система', ('auth', 'core', 'backups')),
]


class GuildAdminSite(admin.AdminSite):
    index_title = 'Дашборд'
    # Стандартное меню Django заменено своим (templates/admin/includes/sidebar.html).
    enable_nav_sidebar = False

    def each_context(self, request):
        from .accents import ACCENT_CHOICES, ACCENT_NAMES, GUILD_ACCENT, user_accent
        from .models import SiteSettings

        context = super().each_context(request)
        site_settings = SiteSettings.load()
        context['site_header'] = site_settings.site_name
        context['site_title'] = f'{site_settings.site_name} · управление'
        if context.get('available_apps'):
            context['ga_nav'] = self._build_nav(request, context['available_apps'])

        guild = site_settings.accent_color
        profile = getattr(request.user, 'profile', None) if request.user.is_authenticated else None
        own = profile.accent_color if profile else ''
        context.update({
            'ga_accent': user_accent(request.user, guild),
            # Что отмечено в меню выбора: свой цвет или «Цвет гильдии».
            'ga_accent_choice': own if own in ACCENT_NAMES else GUILD_ACCENT,
            'ga_guild_accent': guild,
            'ga_guild_accent_name': ACCENT_NAMES.get(guild, '').lower(),
            'ga_guild_accent_value': GUILD_ACCENT,
            'ga_accent_choices': ACCENT_CHOICES,
        })
        return context

    def get_urls(self):
        return [
            path('accent/', self.admin_view(require_POST(self.set_accent_view)), name='set_accent'),
        ] + super().get_urls()

    def set_accent_view(self, request):
        """Сохраняет цвет оформления в профиль. Меню в шапке шлёт запрос фоном, без перезагрузки."""
        from profiles.models import Profile
        from .accents import ACCENT_NAMES, GUILD_ACCENT

        color = request.POST.get('accent')
        if color != GUILD_ACCENT and color not in ACCENT_NAMES:
            return HttpResponseBadRequest('Неизвестный цвет')
        # «Цвет гильдии» хранится пустой строкой: тогда цвет меняется вместе с настройкой сайта.
        Profile.objects.update_or_create(user=request.user,
                                         defaults={'accent_color': '' if color == GUILD_ACCENT else color})
        if request.headers.get('X-Requested-With') == 'fetch':
            return HttpResponse(status=204)
        # Без JavaScript форма отправляется обычным образом — возвращаем на ту же страницу.
        next_url = request.POST.get('next', '')
        if not url_has_allowed_host_and_scheme(next_url, {request.get_host()}, require_https=request.is_secure()):
            next_url = reverse('admin:index')
        return redirect(next_url)

    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(request, app_label)
        for app in app_list:
            app['icon'] = APP_ICON.get(app['app_label'], 'folder')
        app_list.sort(key=lambda app: (APP_POSITION.get(app['app_label'], len(APP_ORDER)), app['name']))
        return app_list

    def _build_nav(self, request, available_apps):
        """Группы бокового меню с отметкой раздела, в котором сейчас находимся."""
        path = request.path
        # Таблица активности открывается из раздела профилей, но её адрес лежит внутри пользователей
        # (profiles/admin.py) — на ней подсвечиваем профили, а не «Пользователи».
        on_activity = path.startswith(reverse('admin:activity_management'))

        def is_current(url):
            return bool(url) and not on_activity and path.startswith(url)

        apps = {}
        for app in available_apps:
            models = [{'name': model['name'], 'url': model['admin_url'], 'current': is_current(model['admin_url'])}
                      for model in app['models']]
            apps[app['app_label']] = {
                'name': app['name'],
                'icon': APP_ICON.get(app['app_label'], 'folder'),
                'url': models[0]['url'] if len(models) == 1 else app['app_url'],
                'models': models if len(models) > 1 else [],
                'current': is_current(app['app_url']),
            }
        if on_activity and 'profiles' in apps:
            apps['profiles']['current'] = True

        groups = []
        for title, labels in NAV_GROUPS:
            items = [apps.pop(label) for label in labels if label in apps]
            if items:
                groups.append({'title': title, 'items': items})
        if apps:
            groups.append({'title': 'Прочее', 'items': list(apps.values())})
        return groups

    def index(self, request, extra_context=None):
        from .dashboard import build_dashboard

        extra_context = {**(extra_context or {}), 'dashboard': build_dashboard(request)}
        return super().index(request, extra_context)
