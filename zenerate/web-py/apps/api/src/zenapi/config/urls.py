"""Root URL conf — assembles sub-routers from ``url_confs/``.

Recordings are NOT served here. They are streamed through the authenticated,
tenant-scoped action ``GET /api/v1/test-runs/<id>/recording/`` (see
``TestRunViewSet.recording``) so one tenant can never read another's call audio.
"""
from django.urls import include, path

urlpatterns = [
    path("", include("zenapi.config.url_confs.urls")),
    path("api/v1/email/", include("zenapi.config.url_confs.email")),
    path("api/v1/", include("zenapi.config.url_confs.voice")),
    path("internal/", include("zenlib_agentos.zenlib.reusable_apps.voice_qa.urls.internal")),
]
