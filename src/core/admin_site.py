"""Админ-панель сайта: свой порядок и иконки разделов, название из настроек и дашборд на главной.

Подключается через core.apps.GuildAdminConfig вместо django.contrib.admin, поэтому все
@admin.register и admin.site в проекте работают с этим классом без изменений.
"""
from django.contrib import admin

# Порядок разделов в меню и на главной: сначала повседневные дела гильдии, в конце — служебное.
APP_ORDER = [
    ('reception', '📝'),
    ('profiles', '⭐'),
    ('events', '⚔️'),
    ('auction', '🎯'),
    ('forum', '💬'),
    ('koslist', '☠️'),
    ('notifications', '🔔'),
    ('teamspeak', '🎧'),
    ('auth', '👥'),
    ('core', '⚙️'),
    ('backups', '💾'),
]
APP_POSITION = {label: index for index, (label, _) in enumerate(APP_ORDER)}
APP_ICON = dict(APP_ORDER)


class GuildAdminSite(admin.AdminSite):
    index_title = 'Обзор'

    def each_context(self, request):
        from .models import SiteSettings

        context = super().each_context(request)
        site_name = SiteSettings.load().site_name
        context['site_header'] = site_name
        context['site_title'] = f'{site_name} · управление'
        return context

    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(request, app_label)
        for app in app_list:
            app['icon'] = APP_ICON.get(app['app_label'], '📁')
        app_list.sort(key=lambda app: (APP_POSITION.get(app['app_label'], len(APP_ORDER)), app['name']))
        return app_list

    def index(self, request, extra_context=None):
        from .dashboard import build_dashboard

        extra_context = {**(extra_context or {}), 'dashboard': build_dashboard(request)}
        return super().index(request, extra_context)
