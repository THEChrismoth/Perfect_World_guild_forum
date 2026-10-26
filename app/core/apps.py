from django.apps import AppConfig
# Импорт модулем, а не классом: иначе AdminConfig (у него default=True) тоже окажется
# в этом модуле, и Django не поймёт, какая конфигурация основная для 'core'.
from django.contrib.admin import apps as admin_apps


class CoreConfig(AppConfig):
    # В модуле два класса конфигурации — этот основной для 'core' в INSTALLED_APPS.
    default = True
    name = 'core'
    verbose_name = 'Сайт'

    def ready(self):
        from django.db.models.signals import post_migrate

        from . import signals  # noqa: F401
        from .roles import ensure_moderator_group

        # Без sender: права приложений создаются после миграций каждого из них,
        # группа дополняется на каждом шаге (повторно ничего не дублируется).
        post_migrate.connect(ensure_moderator_group, dispatch_uid='core.ensure_moderator_group')


class GuildAdminConfig(admin_apps.AdminConfig):
    """Подключается в INSTALLED_APPS вместо django.contrib.admin — админка с дашбордом."""
    default = False
    default_site = 'core.admin_site.GuildAdminSite'
