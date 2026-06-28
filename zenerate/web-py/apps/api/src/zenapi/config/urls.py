"""Root URL conf — assembles sub-routers from ``url_confs/``."""
import os

from django.http import FileResponse, Http404
from django.urls import include, path

_RECORDINGS_DIR = os.environ.get("RECORDINGS_DIR", "/recordings")


def _serve_recording(request, filename):
    if "/" in filename or "\\" in filename or not filename.endswith(".wav"):
        raise Http404("Not found")
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
    path("recordings/<str:filename>", _serve_recording, name="serve-recording"),
]
