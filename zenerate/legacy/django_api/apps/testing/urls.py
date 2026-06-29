from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ScenarioViewSet, TestRunViewSet

router = DefaultRouter()
router.register(r"scenarios", ScenarioViewSet, basename="scenario")
router.register(r"test-runs", TestRunViewSet, basename="test-run")

urlpatterns = [
    path("", include(router.urls)),
]
