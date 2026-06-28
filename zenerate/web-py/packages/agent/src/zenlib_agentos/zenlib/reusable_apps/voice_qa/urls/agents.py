from rest_framework.routers import DefaultRouter
from ..views import AgentViewSet, CallViewSet

router = DefaultRouter()
router.register(r"agents", AgentViewSet, basename="agent")
router.register(r"calls", CallViewSet, basename="call")
urlpatterns = router.urls
