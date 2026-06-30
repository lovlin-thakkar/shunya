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
                  "voice_id", "target_type", "el_agent_id", "dynamic_variables",
                  "yaml_content", "status", "created_at", "updated_at"]
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
    compatible_agents = serializers.SerializerMethodField()
    compatible_agent_ids = serializers.PrimaryKeyRelatedField(
        source="compatible_agents",
        queryset=Agent.objects.all(),
        many=True,
        write_only=True,
        required=False,
    )

    def get_compatible_agents(self, obj):
        return list(obj.compatible_agents.values_list("name", flat=True))

    def update(self, instance, validated_data):
        agents = validated_data.pop("compatible_agents", None)
        instance = super().update(instance, validated_data)
        if agents is not None:
            instance.compatible_agents.set(agents)
        return instance

    def create(self, validated_data):
        agents = validated_data.pop("compatible_agents", [])
        instance = super().create(validated_data)
        if agents:
            instance.compatible_agents.set(agents)
        return instance

    class Meta:
        model = Scenario
        fields = ["id", "name", "description", "yaml_content", "persona",
                  "steps", "assertions", "rubric", "compatible_agents", "compatible_agent_ids", "created_at", "updated_at"]
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
    agent_name = serializers.CharField(source="agent.name", read_only=True)

    class Meta:
        model = TestRun
        fields = ["id", "agent", "agent_name", "scenario", "scenario_name", "mode", "status",
                  "started_at", "completed_at", "created_at", "observer_url",
                  "error_message", "disconnect_reason", "live_scores", "result"]
        read_only_fields = ["id", "agent_name", "scenario_name", "status", "started_at", "completed_at",
                            "created_at", "observer_url", "error_message", "disconnect_reason",
                            "live_scores", "result"]


class AlertConfigSerializer(serializers.ModelSerializer):
    def validate_webhook_url(self, value):
        import ipaddress
        import socket
        from urllib.parse import urlparse
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https"):
            raise serializers.ValidationError("Webhook URL must use http or https.")
        hostname = parsed.hostname or ""
        # Block private/loopback/link-local hostnames by name
        blocked_names = {"localhost", "metadata.google.internal", "169.254.169.254"}
        if hostname.lower() in blocked_names:
            raise serializers.ValidationError("Webhook URL must not target internal hosts.")
        # Resolve and block private IP ranges; unresolvable hosts are not reachable
        try:
            ip = ipaddress.ip_address(socket.gethostbyname(hostname))
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise serializers.ValidationError("Webhook URL must not target private or internal IP addresses.")
        except socket.gaierror:
            pass  # Host doesn't resolve → can't reach private services
        return value

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
