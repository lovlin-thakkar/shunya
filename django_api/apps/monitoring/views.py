from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import AlertConfig, AlertEvent
from .serializers import AlertConfigSerializer, AlertEventSerializer


class AlertConfigViewSet(viewsets.ModelViewSet):
    serializer_class = AlertConfigSerializer

    def get_queryset(self):
        return AlertConfig.objects.select_related("agent")


class AlertEventViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AlertEventSerializer

    def get_queryset(self):
        return AlertEvent.objects.select_related("alert_config", "call")
