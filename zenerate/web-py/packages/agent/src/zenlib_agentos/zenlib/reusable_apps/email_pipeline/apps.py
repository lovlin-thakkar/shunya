from django.apps import AppConfig


class EmailPipelineConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "zenlib_agentos.zenlib.reusable_apps.email_pipeline"
    label = "email_pipeline"
    verbose_name = "Email Pipeline"
