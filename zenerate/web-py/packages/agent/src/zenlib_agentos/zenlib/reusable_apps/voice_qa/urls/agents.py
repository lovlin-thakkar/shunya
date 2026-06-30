from django.urls import path
from rest_framework.routers import DefaultRouter

from ..views import AgentViewSet, CallViewSet, ElevenLabsIntegrationView

router = DefaultRouter()
router.register(r"agents", AgentViewSet, basename="agent")
router.register(r"calls", CallViewSet, basename="call")

urlpatterns = router.urls + [
    path("integrations/elevenlabs/", ElevenLabsIntegrationView.as_view(),
         name="elevenlabs-integration"),
]
