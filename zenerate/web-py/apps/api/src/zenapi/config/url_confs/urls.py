"""Base URLs: admin, health, knox auth."""

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def health(_request):
    return JsonResponse({"ok": True})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("api/auth/", include("knox.urls")),
    path("api/v1/", include("zenapi.config.url_confs.voice")),
    path("internal/", include("zenlib_agentos.zenlib.reusable_apps.voice_qa.urls.internal")),
]
