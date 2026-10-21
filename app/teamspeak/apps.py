from django.apps import AppConfig


class TeamSpeakConfig(AppConfig):
    name = 'teamspeak'
    verbose_name = 'TeamSpeak'

    def ready(self):
        from . import signals  # noqa: F401
