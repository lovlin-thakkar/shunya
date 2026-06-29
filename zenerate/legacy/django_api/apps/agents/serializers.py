from rest_framework import serializers
from .models import Agent, Call, Transcript, CallMetric


class AgentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Agent
        fields = ["id", "name", "description", "system_prompt", "greeting",
                  "voice_id", "yaml_content", "status", "created_at", "updated_at"]
        read_only_fields = ["id", "yaml_content", "created_at", "updated_at"]


class CallSerializer(serializers.ModelSerializer):
    class Meta:
        model = Call
        fields = ["id", "agent", "source", "daily_room_url", "daily_room_name",
                  "status", "started_at", "ended_at", "created_at"]
        read_only_fields = ["id", "created_at"]


class TranscriptSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transcript
        fields = ["id", "call", "turns", "created_at"]
        read_only_fields = ["id", "created_at"]


class CallMetricSerializer(serializers.ModelSerializer):
    class Meta:
        model = CallMetric
        fields = ["id", "call", "name", "value", "created_at"]
        read_only_fields = ["id", "created_at"]
