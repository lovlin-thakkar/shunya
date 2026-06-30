"""Root URL conf — assembles sub-routers from ``url_confs/``."""
import os

from django.http import FileResponse, Http404
from django.urls import include, path
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

_RECORDINGS_DIR = os.environ.get("RECORDINGS_DIR", "/recordings")


class _RecordingView(APIView):
    """Serve a WAV recording — requires Api-Key auth and tenant ownership."""
    permission_classes = [IsAuthenticated]

    def get(self, request, filename):
        from zenlib_agentos.zenlib.reusable_apps.voice_qa.models import TestRun
        from zenlib.reusable_apps.multitenant import context

        if "/" in filename or "\\" in filename or not filename.endswith(".wav"):
            raise Http404("Not found")

        # Derive run_id from filename (format: <run-uuid>.wav)
        run_id = filename[:-4]
        tenant = context.current_tenant.get()
        try:
            TestRun.objects.get(id=run_id, agent__tenant=tenant)
        except (TestRun.DoesNotExist, Exception):
            raise Http404("Recording not found")

        path_on_disk = os.path.join(_RECORDINGS_DIR, filename)
        if not os.path.isfile(path_on_disk):
            raise Http404("Recording not found")
        try:
            f = open(path_on_disk, "rb")
        except OSError:
            raise Http404("Could not open recording")
        return FileResponse(f, content_type="audio/wav")

urlpatterns = [
    path("", include("zenapi.config.url_confs.urls")),
    path("api/v1/email/", include("zenapi.config.url_confs.email")),
    path("api/v1/", include("zenapi.config.url_confs.voice")),
    path("internal/", include("zenlib_agentos.zenlib.reusable_apps.voice_qa.urls.internal")),
    path("recordings/<str:filename>", _RecordingView.as_view(), name="serve-recording"),
]
