from django.apps import AppConfig


class BackupsConfig(AppConfig):
    name = 'backups'
    verbose_name = 'Резервные копии'

    def ready(self):
        from . import signals  # noqa: F401
