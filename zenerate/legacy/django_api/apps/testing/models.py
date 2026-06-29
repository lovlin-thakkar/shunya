import uuid

from django.db import models

from apps.agents.models import Agent, Call


class Scenario(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True, default="")
    yaml_content = models.TextField()
    persona = models.TextField()
    steps = models.JSONField(default=list)       # [{text, quirks: [str]}]
    assertions = models.JSONField(default=list)  # [str]
    rubric = models.JSONField(default=dict)             # {field: weight} overrides
    compatible_agents = models.JSONField(default=list)  # agent names; empty = any agent
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class TestRun(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued"
        RUNNING = "running"
        COMPLETED = "completed"
        FAILED = "failed"

    class Mode(models.TextChoices):
        TEXT = "text"
        AUDIO = "audio"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="test_runs")
    scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE, related_name="test_runs")
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.TEXT)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    celery_task_id = models.CharField(max_length=255, blank=True, default="")
    call = models.OneToOneField(
        Call, on_delete=models.SET_NULL, null=True, blank=True, related_name="test_run"
    )  # set for audio mode
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Pre-auth Daily.co join link; set at call-start so observers can join mid-run
    observer_url = models.URLField(blank=True, default="", max_length=500)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"TestRun {self.id} ({self.scenario.name}, {self.mode})"


class TestResult(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    test_run = models.OneToOneField(TestRun, on_delete=models.CASCADE, related_name="result")
    passed = models.BooleanField(default=False)
    transcript = models.JSONField(default=list)          # [{speaker, text, ts_ms, quirks}]
    assertion_results = models.JSONField(default=list)   # [{assertion, passed}]
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"Result {status} for {self.test_run_id}"


class JudgeScore(models.Model):
    RUBRIC_FIELDS = [
        "instruction_following",
        "goal_completion",
        "interruption_handling",
        "tool_call_accuracy",
        "csat_tone",
        "safety",
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    test_result = models.ForeignKey(TestResult, on_delete=models.CASCADE, related_name="scores")
    field = models.CharField(max_length=50)
    score = models.FloatField()      # 0.0–1.0
    reasoning = models.TextField()
    passed = models.BooleanField()  # score >= 0.7
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("test_result", "field")]

    def __str__(self):
        return f"{self.field}: {self.score:.1f}"
