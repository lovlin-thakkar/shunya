from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AlertConfigViewSet, AlertEventViewSet

router = DefaultRouter()
router.register(r"alerts", AlertConfigViewSet, basename="alert")
router.register(r"alert-events", AlertEventViewSet, basename="alert-event")

urlpatterns = [
    path("", include(router.urls)),
]
