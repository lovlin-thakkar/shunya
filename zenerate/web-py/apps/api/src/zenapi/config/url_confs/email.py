"""URL config for the email pipeline app.

Mounted at ``/api/v1/email/`` by ``zenapi.config.urls``. This is a thin
forwarder to the app's own ``urls.py`` so adding new routes happens in
one place.
"""

from django.urls import include

# DRF router lives inside the app; we just re-export its urlpatterns.
urlpatterns = [
    include("zenlib_agentos.zenlib.reusable_apps.email_pipeline.urls"),
]

# Django expects a flat list of URLPattern objects, not `include()` results.
# Unwrap so this module behaves as a urlconf.
from zenlib_agentos.zenlib.reusable_apps.email_pipeline.urls import (  # noqa: E402
    urlpatterns as _email_urlpatterns,
)

urlpatterns = _email_urlpatterns
