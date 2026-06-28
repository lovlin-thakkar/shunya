import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "zenapi.config.settings")

app = Celery("voice_qa")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
