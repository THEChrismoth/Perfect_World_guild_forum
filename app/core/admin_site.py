"""Админ-панель сайта: свой порядок и иконки разделов, боковое меню, название из настроек и дашборд на главной.

Подключается через core.apps.GuildAdminConfig вместо django.contrib.admin, поэтому все
@admin.register и admin.site в проекте работают с этим классом без изменений.
"""
from django.contrib import admin
from django.urls import reverse

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
        from .models import SiteSettings

        context = super().each_context(request)
        site_name = SiteSettings.load().site_name
        context['site_header'] = site_name
        context['site_title'] = f'{site_name} · управление'
        if context.get('available_apps'):
            context['ga_nav'] = self._build_nav(request, context['available_apps'])
        return context

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
