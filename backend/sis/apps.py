from django.apps import AppConfig

class SisConfig(AppConfig):
    name = "sis"
    def ready(self):
        from . import signals  # noqa
