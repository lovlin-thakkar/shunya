from rest_framework import serializers
from .models import Scenario, TestRun, TestResult, JudgeScore


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

    class Meta:
        model = TestRun
        fields = ["id", "agent", "scenario", "mode", "status",
                  "started_at", "completed_at", "created_at", "observer_url", "result"]
        read_only_fields = ["id", "status", "started_at", "completed_at", "created_at",
                            "observer_url", "result"]
