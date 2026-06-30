"""Django settings — single-file for the baseline.

The production zenafide repo splits this across ``base.py``, ``db_conf.py``,
``aws.py``, ``third_party_conf.py``, ``app_conf.py``, and a ``django/``
subpackage. For the take-home we collapse them into one file — the layout
still matches (settings module path = ``zenapi.config.settings``), so when
you merge this back into the production repo, only this file needs to be
split.
"""

import os
from pathlib import Path

# apps/api/src/zenapi/config/settings/__init__.py → apps/api/
BASE_DIR = Path(__file__).resolve().parents[4]

_DEV_SECRET_KEY = "dev-secret-do-not-use-in-prod"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", _DEV_SECRET_KEY)
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = ["*"] if DEBUG else os.environ.get("ALLOWED_HOSTS", "").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "knox",
    "corsheaders",
    "polymorphic",
    # Internal library — Tenant + RLS plumbing
    "zenlib.reusable_apps.multitenant.apps.MultitenantConfig",
    # Email pipeline scaffold (leave as-is)
    "zenlib_agentos.zenlib.reusable_apps.email_pipeline.apps.EmailPipelineConfig",
    # Voice QA platform
    "zenlib_agentos.zenlib.reusable_apps.voice_qa.apps.VoiceQAConfig",
]

# Order matters: context middleware sets the ContextVar that RLS middleware reads.
# TenantAPIKeyMiddleware must sit between context and RLS to handle Api-Key header.
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "zenlib.reusable_apps.multitenant.middleware.MultitenantContextMiddleware",
    "zenlib_agentos.zenlib.reusable_apps.voice_qa.middleware.TenantAPIKeyMiddleware",
    "zenlib.reusable_apps.multitenant.middleware.MultitenantRLSMiddleware",
]

ROOT_URLCONF = "zenapi.config.urls"
WSGI_APPLICATION = "zenapi.wsgi.application"
ASGI_APPLICATION = "zenapi.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "zenapi"),
        "USER": os.environ.get("DB_USER", "zen"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "zen"),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
        # RLS needs every request to run inside a transaction so SET LOCAL
        # scopes correctly.
        "ATOMIC_REQUESTS": True,
    }
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "knox.auth.TokenAuthentication",
        "zenlib_agentos.zenlib.reusable_apps.voice_qa.authentication.TenantAPIKeyAuthentication",
        "zenlib_agentos.zenlib.reusable_apps.voice_qa.authentication.ServiceTokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        # Tenant-aware: stock UserRateThrottle 500s on ServiceAccount (no pk).
        "zenlib_agentos.zenlib.reusable_apps.voice_qa.throttling.ScopedIdentityUserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "user": "300/min",
    },
    "DEFAULT_PAGINATION_CLASS": (
        "rest_framework.pagination.PageNumberPagination"
    ),
    "PAGE_SIZE": 50,
}

REST_KNOX = {"TOKEN_TTL": None}

# Shared by ServiceTokenAuthentication. Rotate per environment.
_DEV_SERVICE_TOKEN = "dev-service-token-change-me"
SERVICE_TOKEN = os.environ.get("SERVICE_TOKEN", _DEV_SERVICE_TOKEN)

# Voice QA / Pipecat
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
DAILY_API_KEY = os.environ.get("DAILY_API_KEY", "")
PIPECAT_SERVER_URL = os.environ.get("PIPECAT_SERVER_URL", "http://localhost:8001")
# Caller service — RemoteAudioCaller posts directly here to drive remote
# ElevenLabs agents over WebSocket (no Pipecat/Daily room involved).
CALLER_SERVER_URL = os.environ.get("CALLER_SERVER_URL", "http://localhost:8002")
RECORDINGS_DIR = os.environ.get("RECORDINGS_DIR", "/recordings")

# Celery
CELERY_BROKER_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]

# CORS: explicit allowlist, not wildcard. Set UI_URL env var in production to the real domain.
# CORS_ALLOW_CREDENTIALS=True is required for Knox cookie auth (future); safe because we use
# an explicit CORS_ALLOWED_ORIGINS list, not CORS_ALLOW_ALL_ORIGINS.
CORS_ALLOWED_ORIGINS = [os.environ.get("UI_URL", "http://localhost:3000")]
CORS_ALLOW_CREDENTIALS = True

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "static/"

if not DEBUG:
    from django.core.exceptions import ImproperlyConfigured
    if SECRET_KEY == _DEV_SECRET_KEY:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set in production.")
    if SERVICE_TOKEN == _DEV_SERVICE_TOKEN:
        raise ImproperlyConfigured("SERVICE_TOKEN must be set in production.")
