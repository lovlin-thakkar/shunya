from rest_framework.routers import DefaultRouter
from ..views import TestRunViewSet

router = DefaultRouter()
router.register(r"test-runs", TestRunViewSet, basename="test-run")
urlpatterns = router.urls
