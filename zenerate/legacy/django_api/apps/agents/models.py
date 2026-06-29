import uuid

from django.db import models


class Agent(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active"
        INACTIVE = "inactive"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    system_prompt = models.TextField()
    # Optional first utterance: if set, the agent speaks this before the caller's
    # first turn (audio: triggered on participant-join; text: prepended to transcript).
    greeting = models.TextField(blank=True, default="")
    voice_id = models.CharField(max_length=255, blank=True, default="")  # ElevenLabs voice ID
    yaml_content = models.TextField(blank=True, default="")  # raw source YAML for audit/display
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class Call(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress"
        COMPLETED = "completed"
        FAILED = "failed"

    class Source(models.TextChoices):
        HUMAN = "human"
        TEST_TEXT = "test_text"
        TEST_AUDIO = "test_audio"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="calls")
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.HUMAN)
    daily_room_url = models.URLField(blank=True, default="")
    daily_room_name = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_PROGRESS)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Call {self.id} ({self.agent.name})"


class Transcript(models.Model):
    # turns: [{speaker: "agent"|"caller", text: str, ts_ms: int, quirks: [str]}]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    call = models.OneToOneField(Call, on_delete=models.CASCADE, related_name="transcript")
    turns = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Transcript for {self.call_id}"


class CallMetric(models.Model):
    """Flexible key-value metric store per call. One row per metric name."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    call = models.ForeignKey(Call, on_delete=models.CASCADE, related_name="metrics")
    name = models.CharField(max_length=64)
    value = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("call", "name")]
        ordering = ["name"]

    def __str__(self):
        return f"{self.name}={self.value} (call {self.call_id})"
