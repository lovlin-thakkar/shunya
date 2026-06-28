from django.apps import AppConfig


class MultitenantConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "zenlib.reusable_apps.multitenant"
    label = "multitenant"
    verbose_name = "Multitenant"
