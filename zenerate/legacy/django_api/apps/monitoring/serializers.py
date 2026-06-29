from rest_framework import serializers
from .models import AlertConfig, AlertEvent


class AlertConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertConfig
        fields = ["id", "agent", "metric_name", "operator", "threshold",
                  "webhook_url", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]


class AlertEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertEvent
        fields = ["id", "alert_config", "call", "triggered_at", "metric_value", "payload_sent"]
        read_only_fields = ["id", "triggered_at"]
