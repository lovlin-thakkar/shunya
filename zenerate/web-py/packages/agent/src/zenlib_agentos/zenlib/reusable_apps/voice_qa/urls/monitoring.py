from rest_framework.routers import DefaultRouter
from ..views import AlertConfigViewSet, AlertEventViewSet

router = DefaultRouter()
router.register(r"alerts", AlertConfigViewSet, basename="alert")
router.register(r"alert-events", AlertEventViewSet, basename="alert-event")
urlpatterns = router.urls
