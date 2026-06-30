import hashlib
import secrets
import uuid

from django.db import models

from zenlib.reusable_apps.multitenant import context as _mt_context
from zenlib.reusable_apps.multitenant.models import ActivityTenantBaseModel


class UUIDTenantModel(ActivityTenantBaseModel):
    """Abstract base for models with a UUID PK.

    ActivityTenantBaseModel._populate_tenant_if_needed() returns early if self.pk
    is truthy, which is always the case for UUID fields with default=uuid.uuid4
    (the UUID is generated at instantiation, before the first save). This override
    uses self._state.adding to detect genuinely new instances instead.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta(ActivityTenantBaseModel.Meta):
        abstract = True

    def save(self, *args, **kwargs):
        if not self.tenant_id and self._state.adding:
            tenant = _mt_context.current_tenant.get()
            if tenant is not None:
                self.tenant_id = tenant.id
        super().save(*args, **kwargs)


class TenantAPIKey(UUIDTenantModel):
    """Per-tenant API key for CLI / external callers. Hashed at rest."""

    key_hash = models.CharField(max_length=64, unique=True)
    key_prefix = models.CharField(max_length=8)

    class Meta(ActivityTenantBaseModel.Meta):
        app_label = "voice_qa"

    @classmethod
    def generate(cls, tenant):
        raw = secrets.token_hex(32)
        prefix = raw[:8]
        key_hash = hashlib.sha256(raw.encode()).hexdigest()
        obj = cls.objects.create(tenant=tenant, key_hash=key_hash, key_prefix=prefix)
        return obj, raw

    @classmethod
    def authenticate(cls, raw_key: str):
        """Return tenant for a valid raw key, or None.

        Must bypass Postgres RLS for the key-hash lookup: at authentication
        time the tenant context is not yet established, so
        app.current_tenant_id is 0 (or stale from a previous request) and
        the multitenant_rls__current_tenant_only policy would filter out all
        rows. The multitenant_rls__cross_tenant escape hatch is used here for
        exactly this bootstrap case — we're looking up BY the key (unique),
        not filtering by tenant.
        """
        from django.db import connection
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        try:
            with connection.cursor() as cur:
                cur.execute("SELECT set_config('app.cross_tenant_access', 'true', false)")
            try:
                return cls.objects.select_related("tenant").get(key_hash=key_hash).tenant
            finally:
                with connection.cursor() as cur:
                    cur.execute("SELECT set_config('app.cross_tenant_access', 'false', false)")
        except cls.DoesNotExist:
            return None

    def __str__(self):
        return f"{self.key_prefix}... ({self.tenant})"


class Agent(UUIDTenantModel):
    class Status(models.TextChoices):
        ACTIVE = "active"
        INACTIVE = "inactive"

    class TargetType(models.TextChoices):
        # The agent under test is driven by AgentChat (Claude Haiku, in-process)
        # using system_prompt/greeting. Text-only; no audio pipeline.
        BUILTIN = "builtin", "Built-in (Text)"
        # The agent under test is a customer's deployed ElevenLabs Conversational
        # AI agent, reached over WebSocket by el_agent_id. system_prompt/voice_id
        # are ignored for this type — the remote agent owns its own brain/voice.
        ELEVENLABS = "elevenlabs", "Remote ElevenLabs agent"

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    system_prompt = models.TextField()
    greeting = models.TextField(blank=True, default="")
    voice_id = models.CharField(max_length=255, blank=True, default="")
    yaml_content = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    target_type = models.CharField(
        max_length=20, choices=TargetType.choices, default=TargetType.BUILTIN
    )
    # ElevenLabs Conversational AI agent_id — only used when target_type is ELEVENLABS.
    el_agent_id = models.CharField(max_length=255, blank=True, default="")
    # Dynamic variables injected into conversation_initiation_client_data for ElevenLabs agents.
    # Keys/values must match what the agent's prompt template requires (e.g. {"company_name": "Acme"}).
    dynamic_variables = models.JSONField(default=dict, blank=True)

    class Meta(ActivityTenantBaseModel.Meta):
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class ElevenLabsCredential(UUIDTenantModel):
    """Per-tenant ElevenLabs API key used to list and drive the tenant's own
    Conversational AI agents.

    Write-only: the raw key is never returned through the API — callers only see
    `key_hint` (a masked preview) and whether a key is configured. At-rest DB
    encryption is a follow-up (would require adding the `cryptography` dep).
    """

    api_key = models.TextField()
    key_hint = models.CharField(max_length=16, blank=True, default="")  # e.g. "sk_0…a1b2"

    class Meta(ActivityTenantBaseModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["tenant"], name="uniq_el_credential_per_tenant"),
        ]

    def __str__(self) -> str:
        return f"ElevenLabs key for {self.tenant} ({self.key_hint})"


class Call(UUIDTenantModel):
    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress"
        COMPLETED = "completed"
        FAILED = "failed"

    class Source(models.TextChoices):
        HUMAN = "human"
        TEST_TEXT = "test_text"
        TEST_AUDIO = "test_audio"

    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="calls")
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.HUMAN)
    daily_room_url = models.URLField(blank=True, default="")
    daily_room_name = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_PROGRESS)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta(ActivityTenantBaseModel.Meta):
        ordering = ["-created_at"]

    def __str__(self):
        return f"Call {self.id} ({self.agent.name})"


class Transcript(UUIDTenantModel):
    # turns: [{speaker: "agent"|"caller", text: str, ts_ms: int, quirks: [str]}]
    call = models.OneToOneField(Call, on_delete=models.CASCADE, related_name="transcript")
    turns = models.JSONField(default=list)

    class Meta(ActivityTenantBaseModel.Meta):
        pass

    def __str__(self):
        return f"Transcript for {self.call_id}"


class CallMetric(UUIDTenantModel):
    """Flexible key-value metric store per call. One row per metric name."""

    call = models.ForeignKey(Call, on_delete=models.CASCADE, related_name="metrics")
    name = models.CharField(max_length=64)
    value = models.FloatField()

    class Meta(ActivityTenantBaseModel.Meta):
        unique_together = [("call", "name")]
        ordering = ["name"]

    def __str__(self):
        return f"{self.name}={self.value} (call {self.call_id})"


class Scenario(UUIDTenantModel):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    yaml_content = models.TextField()
    persona = models.TextField()
    steps = models.JSONField(default=list)       # [{text, raw, quirks: [{tag, value}]}]
    assertions = models.JSONField(default=list)  # [str]
    rubric = models.JSONField(default=dict)      # {field: weight}
    compatible_agents = models.ManyToManyField(
        "Agent", blank=True, related_name="compatible_scenarios"
    )  # empty = compatible with any agent

    class Meta(ActivityTenantBaseModel.Meta):
        ordering = ["name"]
        unique_together = [("tenant", "name")]

    def __str__(self):
        return self.name


class TestRun(UUIDTenantModel):
    class Status(models.TextChoices):
        QUEUED = "queued"
        RUNNING = "running"
        COMPLETED = "completed"
        FAILED = "failed"

    class Mode(models.TextChoices):
        TEXT = "text"
        AUDIO = "audio"

    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="test_runs")
    scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE, related_name="test_runs")
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.TEXT)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    celery_task_id = models.CharField(max_length=255, blank=True, default="")
    call = models.OneToOneField(
        Call, on_delete=models.SET_NULL, null=True, blank=True, related_name="test_run"
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    # Pre-auth Daily.co join link; set at call-start so observers can join mid-run
    observer_url = models.URLField(blank=True, default="", max_length=500)
    error_message = models.TextField(blank=True, default="")
    # Set when the remote agent (ElevenLabs) closed the WS mid-conversation — the
    # run still completes with a truncated transcript; this explains why.
    disconnect_reason = models.CharField(max_length=255, blank=True, default="")
    # During-call scores from Scorer (remote mode), updated turn-by-turn:
    # {"turn": int, "scores": [{field, score, passed, reasoning}]}.
    # Promoted to permanent JudgeScore rows by _promote_live_scores() after the call.
    live_scores = models.JSONField(default=dict)

    class Meta(ActivityTenantBaseModel.Meta):
        ordering = ["-created_at"]

    def __str__(self):
        return f"TestRun {self.id} ({self.scenario.name}, {self.mode})"


class TestResult(UUIDTenantModel):
    test_run = models.OneToOneField(TestRun, on_delete=models.CASCADE, related_name="result")
    passed = models.BooleanField(default=False)
    transcript = models.JSONField(default=list)        # [{speaker, text, ts_ms, quirks}]
    assertion_results = models.JSONField(default=list) # [{assertion, passed}]

    class Meta(ActivityTenantBaseModel.Meta):
        pass

    def __str__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"Result {status} for {self.test_run_id}"


class JudgeScore(UUIDTenantModel):
    RUBRIC_FIELDS = [
        "instruction_following",
        "goal_completion",
        "interruption_handling",
        "tool_call_accuracy",
        "csat_tone",
        "safety",
    ]

    test_result = models.ForeignKey(TestResult, on_delete=models.CASCADE, related_name="scores")
    field = models.CharField(max_length=50)
    score = models.FloatField()      # 0.0–1.0
    reasoning = models.TextField()
    passed = models.BooleanField()   # score >= 0.7

    class Meta(ActivityTenantBaseModel.Meta):
        unique_together = [("test_result", "field")]

    def __str__(self):
        return f"{self.field}: {self.score:.1f}"


class AlertConfig(UUIDTenantModel):
    class Operator(models.TextChoices):
        GT = "gt"
        LT = "lt"
        GTE = "gte"
        LTE = "lte"
        EQ = "eq"

    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="alerts")
    metric_name = models.CharField(max_length=100)
    operator = models.CharField(max_length=5, choices=Operator.choices)
    threshold = models.FloatField()
    webhook_url = models.URLField()
    is_active = models.BooleanField(default=True)

    class Meta(ActivityTenantBaseModel.Meta):
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.agent.name}: {self.metric_name} {self.operator} {self.threshold}"

    def evaluate(self, value: float) -> bool:
        ops = {
            "gt": value > self.threshold,
            "lt": value < self.threshold,
            "gte": value >= self.threshold,
            "lte": value <= self.threshold,
            "eq": value == self.threshold,
        }
        return ops[self.operator]


class AlertEvent(UUIDTenantModel):
    alert_config = models.ForeignKey(AlertConfig, on_delete=models.CASCADE, related_name="events")
    call = models.ForeignKey(Call, on_delete=models.CASCADE, related_name="alert_events")
    metric_value = models.FloatField()
    payload_sent = models.JSONField(default=dict)

    class Meta(ActivityTenantBaseModel.Meta):
        ordering = ["-created_at"]

    def __str__(self):
        return f"Alert {self.alert_config} fired for call {self.call_id}"
