"""Voice QA API routes — agents, scenarios, test runs, monitoring, internal."""

from django.urls import include, path

urlpatterns = [
    path("", include("zenlib_agentos.zenlib.reusable_apps.voice_qa.urls.agents")),
    path("", include("zenlib_agentos.zenlib.reusable_apps.voice_qa.urls.scenarios")),
    path("", include("zenlib_agentos.zenlib.reusable_apps.voice_qa.urls.test_runs")),
    path("", include("zenlib_agentos.zenlib.reusable_apps.voice_qa.urls.monitoring")),
]
