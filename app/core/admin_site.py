"""Админ-панель сайта: свой порядок и иконки разделов, боковое меню, название из настроек и дашборд на главной.

Подключается через core.apps.GuildAdminConfig вместо django.contrib.admin, поэтому все
@admin.register и admin.site в проекте работают с этим классом без изменений.
"""
from django.contrib import admin
from django.urls import path, reverse
from django.views.decorators.http import require_POST

# Порядок разделов в меню: сначала повседневные дела гильдии, в конце — служебное.
# Иконки — имена из core/templatetags/ga_admin.py.
APP_ORDER = [
    ('reception', 'file-text'),
    ('profiles', 'table'),
    ('events', 'swords'),
    ('skirmishes', 'zap'),
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
    ('Гильдия', ('reception', 'profiles', 'events', 'skirmishes', 'auction', 'koslist')),
    ('Сообщество', ('forum', 'notifications', 'teamspeak')),
    ('Система', ('auth', 'core', 'backups')),
]


class GuildAdminSite(admin.AdminSite):
    index_title = 'Дашборд'
    # Стандартное меню Django заменено своим (templates/admin/includes/sidebar.html).
    enable_nav_sidebar = False

    def each_context(self, request):
        from .accents import accent_menu
        from .models import SiteSettings

        context = super().each_context(request)
        site_settings = SiteSettings.load()
        context['site_header'] = site_settings.site_name
        context['site_title'] = f'{site_settings.site_name} · управление'
        if context.get('available_apps'):
            context['ga_nav'] = self._build_nav(request, context['available_apps'])

        menu = accent_menu(request.user, site_settings.accent_color)
        context.update({
            'ga_accent': menu['accent'],
            # Что отмечено в меню выбора: свой цвет или «Цвет гильдии».
            'ga_accent_choice': menu['choice'],
            'ga_guild_accent': menu['guild'],
            'ga_guild_accent_name': menu['guild_name'],
            'ga_guild_accent_value': menu['guild_value'],
            'ga_accent_choices': menu['choices'],
        })
        return context

    def get_urls(self):
        return [
            path('accent/', self.admin_view(require_POST(self.set_accent_view)), name='set_accent'),
        ] + super().get_urls()

    def set_accent_view(self, request):
        """Сохраняет цвет оформления из меню в шапке админки (та же логика, что и на сайте)."""
        from .accents import handle_accent_post

        return handle_accent_post(request, reverse('admin:index'))

    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(request, app_label)
        for app in app_list:
            app['icon'] = APP_ICON.get(app['app_label'], 'folder')
            if app['app_label'] == 'events':
                positions = {'EventType': 0, 'EventNotification': 1}
                app['models'].sort(key=lambda model: positions.get(model['object_name'], 2))
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
