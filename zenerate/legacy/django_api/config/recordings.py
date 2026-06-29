"""Serve audio-test call recordings written by the caller bot to /recordings."""
import os

from django.http import FileResponse, Http404

RECORDINGS_DIR = os.environ.get("RECORDINGS_DIR", "/recordings")


def serve_recording(request, filename):
    # Only allow plain <name>.wav — no path traversal.
    if "/" in filename or "\\" in filename or not filename.endswith(".wav"):
        raise Http404("Not found")
    path = os.path.join(RECORDINGS_DIR, filename)
    if not os.path.isfile(path):
        raise Http404("Recording not found")
    try:
        f = open(path, "rb")
    except OSError:
        raise Http404("Could not open recording")
    return FileResponse(f, content_type="audio/wav")
