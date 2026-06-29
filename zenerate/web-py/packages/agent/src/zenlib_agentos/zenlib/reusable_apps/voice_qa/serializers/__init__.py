from rest_framework import serializers
from ..models import (
    Agent, Call, Transcript, CallMetric,
    Scenario, TestRun, TestResult, JudgeScore,
    AlertConfig, AlertEvent,
)


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


class ScenarioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Scenario
        fields = ["id", "name", "description", "yaml_content", "persona",
                  "steps", "assertions", "rubric", "compatible_agents", "created_at", "updated_at"]
        read_only_fields = ["id", "steps", "assertions", "compatible_agents", "created_at", "updated_at"]


class JudgeScoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = JudgeScore
        fields = ["field", "score", "reasoning", "passed"]


class TestResultSerializer(serializers.ModelSerializer):
    scores = JudgeScoreSerializer(many=True, read_only=True)

    class Meta:
        model = TestResult
        fields = ["id", "passed", "transcript", "assertion_results", "scores", "created_at"]
        read_only_fields = ["id", "created_at"]


class TestRunSerializer(serializers.ModelSerializer):
    result = TestResultSerializer(read_only=True)
    scenario_name = serializers.CharField(source="scenario.name", read_only=True)

    class Meta:
        model = TestRun
        fields = ["id", "agent", "scenario", "scenario_name", "mode", "status",
                  "started_at", "completed_at", "created_at", "observer_url", "result"]
        read_only_fields = ["id", "scenario_name", "status", "started_at", "completed_at",
                            "created_at", "observer_url", "result"]


class AlertConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertConfig
        fields = ["id", "agent", "metric_name", "operator", "threshold",
                  "webhook_url", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]


class AlertEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertEvent
        fields = ["id", "alert_config", "call", "created_at", "metric_value", "payload_sent"]
        read_only_fields = ["id", "created_at"]
