from django.contrib import admin
from django.urls import path, include

from .recordings import serve_recording

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.agents.urls")),
    path("api/", include("apps.testing.urls")),
    path("api/", include("apps.monitoring.urls")),
    path("internal/", include("apps.agents.internal_urls")),
    path("recordings/<str:filename>", serve_recording),
]
