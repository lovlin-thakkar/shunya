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
    yaml_content = serializers.CharField(allow_blank=True, required=False, default="")
    persona = serializers.CharField(allow_blank=True, required=False, default="")

    class Meta:
        model = Scenario
        fields = ["id", "name", "description", "yaml_content", "persona",
                  "steps", "assertions", "rubric", "compatible_agents", "created_at", "updated_at"]
        read_only_fields = ["id", "compatible_agents", "created_at", "updated_at"]

    def validate(self, data):
        # Auto-generate minimal yaml_content when creating via UI (yaml_content not provided)
        if not data.get("yaml_content"):
            import yaml as _yaml
            doc = {"name": data.get("name", "")}
            if data.get("persona"):
                doc["persona"] = data["persona"]
            steps = data.get("steps", [])
            if steps:
                doc["steps"] = [s.get("raw", s.get("text", "")) if isinstance(s, dict) else s for s in steps]
            if data.get("assertions"):
                doc["assertions"] = data["assertions"]
            if data.get("rubric"):
                doc["rubric"] = data["rubric"]
            data["yaml_content"] = _yaml.dump(doc, allow_unicode=True, default_flow_style=False)
        return data

    def validate_steps(self, value):
        # Accept either plain strings or full step dicts; normalise to [{text, raw, quirks}]
        normalised = []
        for item in value:
            if isinstance(item, str):
                normalised.append({"text": item, "raw": item, "quirks": []})
            elif isinstance(item, dict):
                normalised.append({
                    "text": item.get("text", item.get("raw", "")),
                    "raw": item.get("raw", item.get("text", "")),
                    "quirks": item.get("quirks", []),
                })
            else:
                raise serializers.ValidationError("Each step must be a string or object.")
        return normalised


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
