import httpx
from celery import group as celery_group
from django.conf import settings
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import (
    Agent, Call, Transcript, CallMetric, Scenario, TestRun, TestResult,
    AlertConfig, AlertEvent, ElevenLabsCredential,
)

ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1"
from ..serializers import (
    AgentSerializer, CallSerializer, TranscriptSerializer, CallMetricSerializer,
    ScenarioSerializer, TestRunSerializer, TestResultSerializer,
    AlertConfigSerializer, AlertEventSerializer,
)
from ..services.chat import AgentChat
from ..tasks import run_scenario_task

# Module-level cache: conversation_id → AgentChat. In multi-process deployments use Redis.
_chat_sessions: dict[str, AgentChat] = {}


def _tenant():
    from zenlib.reusable_apps.multitenant import context
    return context.current_tenant.get()


class AgentViewSet(viewsets.ModelViewSet):
    serializer_class = AgentSerializer

    def get_queryset(self):
        return Agent.objects.filter(tenant=_tenant(), status=Agent.Status.ACTIVE)

    def list(self, request, *args, **kwargs):
        # The agents screen only displays the tenant's remote ElevenLabs agents
        # (synced from their account); built-in agents are not surfaced.
        qs = self.get_queryset().filter(target_type=Agent.TargetType.ELEVENLABS)
        return Response(self.get_serializer(qs, many=True).data)

    def create(self, request, *args, **kwargs):
        # Authoring agents in Shunya is removed; agents come from ElevenLabs.
        return Response(
            {"error": "Agents are synced from ElevenLabs, not created here. "
                      "Use POST /api/v1/agents/sync-elevenlabs/."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=False, methods=["post"], url_path="sync-elevenlabs")
    def sync_elevenlabs(self, request):
        """List the tenant's ElevenLabs Conversational AI agents (using their saved
        key) and upsert them as local target_type=elevenlabs Agent rows. Agents
        that disappeared from ElevenLabs are marked inactive."""
        tenant = _tenant()
        cred = ElevenLabsCredential.objects.filter(tenant=tenant).first()
        if not cred:
            return Response(
                {"error": "ElevenLabs is not connected. Add your API key first."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            r = httpx.get(
                f"{ELEVENLABS_API_URL}/convai/agents",
                headers={"xi-api-key": cred.api_key},
                timeout=20,
            )
        except httpx.HTTPError as e:
            return Response({"error": f"Could not reach ElevenLabs: {e}"},
                            status=status.HTTP_502_BAD_GATEWAY)
        if r.status_code == 401:
            return Response(
                {"error": "ElevenLabs rejected the key (needs convai_read permission)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if r.status_code != 200:
            return Response({"error": f"ElevenLabs error {r.status_code}"},
                            status=status.HTTP_502_BAD_GATEWAY)

        remote = r.json().get("agents", [])
        seen = []
        for ra in remote:
            aid = ra.get("agent_id")
            if not aid:
                continue
            Agent.objects.update_or_create(
                tenant=tenant,
                el_agent_id=aid,
                target_type=Agent.TargetType.ELEVENLABS,
                defaults={
                    "name": ra.get("name") or aid,
                    "system_prompt": "",
                    "status": Agent.Status.ACTIVE,
                },
            )
            seen.append(aid)
        # Deactivate agents that no longer exist in the tenant's ElevenLabs account.
        Agent.objects.filter(
            tenant=tenant, target_type=Agent.TargetType.ELEVENLABS,
        ).exclude(el_agent_id__in=seen).update(status=Agent.Status.INACTIVE)

        return Response(AgentSerializer(self.get_queryset(), many=True).data)

    @action(detail=True, methods=["post"], url_path="chat")
    def chat(self, request, pk=None):
        from zenlib.reusable_apps.multitenant import context
        agent = self.get_object()
        message = request.data.get("message", "")
        conversation_id = request.data.get("conversation_id")
        if not message:
            return Response({"error": "message is required"}, status=status.HTTP_400_BAD_REQUEST)
        tenant = context.current_tenant.get()
        # Key on (tenant_id, conversation_id) to prevent cross-tenant session sharing.
        cache_key = f"{tenant.id}:{conversation_id}"
        if cache_key not in _chat_sessions:
            _chat_sessions[cache_key] = AgentChat(agent)
        result = _chat_sessions[cache_key].send(message, conversation_id)
        return Response(result)

    @action(detail=True, methods=["get"], url_path="test-runs")
    def test_runs(self, request, pk=None):
        agent = self.get_object()
        runs = TestRun.objects.filter(agent=agent)
        return Response(TestRunSerializer(runs, many=True).data)

    @action(detail=True, methods=["get"], url_path="metrics")
    def metrics(self, request, pk=None):
        agent = self.get_object()
        metrics = CallMetric.objects.filter(call__agent=agent).select_related("call")
        return Response(CallMetricSerializer(metrics, many=True).data)

    @action(detail=True, methods=["post"], url_path="connect")
    def connect(self, request, pk=None):
        agent = self.get_object()
        try:
            r = httpx.post(
                f"{settings.PIPECAT_SERVER_URL}/connect",
                headers={"X-Service-Token": settings.SERVICE_TOKEN},
                json={
                    "agent_id": str(agent.id),
                    "system_prompt": agent.system_prompt,
                    "voice_id": agent.voice_id,
                    "greeting": agent.greeting,
                    "tenant_id": str(agent.tenant_id),
                },
                timeout=10,
            )
            r.raise_for_status()
            return Response(r.json())
        except httpx.HTTPError as e:
            return Response({"error": f"Voice server unavailable: {e}"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    @action(detail=True, methods=["get", "post"], url_path="alerts")
    def alerts(self, request, pk=None):
        agent = self.get_object()
        if request.method == "GET":
            return Response(AlertConfigSerializer(AlertConfig.objects.filter(agent=agent), many=True).data)
        serializer = AlertConfigSerializer(data={**request.data, "agent": agent.id})
        serializer.is_valid(raise_exception=True)
        serializer.save(agent=agent)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="run-evals")
    def run_evals(self, request, pk=None):
        """Spawn parallel sub-agents: one per scenario, all dispatched simultaneously via Celery group.

        Body (optional):
          scenario_names: ["s1", "s2"]  — subset; omit to run all scenarios
          mode: "text" | "audio"         — default text
        """
        from zenlib.reusable_apps.multitenant import context
        agent = self.get_object()
        mode = request.data.get("mode", TestRun.Mode.TEXT)
        scenario_names = request.data.get("scenario_names") or []
        tenant = context.current_tenant.get()

        from django.db.models import Count, Q
        # Scenarios with no compatible_agents are universal; otherwise must include this agent.
        qs = Scenario.objects.annotate(
            agent_count=Count("compatible_agents", distinct=True)
        ).filter(
            Q(agent_count=0) | Q(compatible_agents=agent)
        ).distinct()
        if scenario_names:
            qs = qs.filter(name__in=scenario_names)

        scenarios = list(qs)
        if not scenarios:
            return Response({"error": "No matching scenarios found"}, status=404)

        # Create all TestRun rows first, then dispatch as a Celery group for true parallelism.
        runs = [
            TestRun.objects.create(agent=agent, scenario=s, mode=mode)
            for s in scenarios
        ]
        task_group = celery_group(
            run_scenario_task.s(str(r.id), tenant.id) for r in runs
        )
        group_result = task_group.apply_async()

        # Persist task IDs for observability
        for run, task in zip(runs, group_result.results):
            run.celery_task_id = task.id
            run.save(update_fields=["celery_task_id"])

        return Response(
            {
                "group_id": group_result.id,
                "runs": TestRunSerializer(runs, many=True).data,
                "parallelism": len(runs),
            },
            status=status.HTTP_201_CREATED,
        )


class CallViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CallSerializer

    def get_queryset(self):
        return Call.objects.filter(tenant=_tenant()).select_related("agent")

    @action(detail=True, methods=["get"], url_path="transcript")
    def transcript(self, request, pk=None):
        call = self.get_object()
        try:
            return Response(TranscriptSerializer(call.transcript).data)
        except Transcript.DoesNotExist:
            return Response({"error": "No transcript yet"}, status=404)

    @action(detail=True, methods=["get"], url_path="metrics")
    def metrics(self, request, pk=None):
        return Response(CallMetricSerializer(CallMetric.objects.filter(call=self.get_object()), many=True).data)


class ScenarioViewSet(viewsets.ModelViewSet):
    serializer_class = ScenarioSerializer

    def get_queryset(self):
        return Scenario.objects.filter(tenant=_tenant())


class TestRunViewSet(viewsets.ModelViewSet):
    serializer_class = TestRunSerializer

    def get_queryset(self):
        return TestRun.objects.filter(tenant=_tenant()).select_related("scenario", "agent").prefetch_related("result__scores")

    def create(self, request):
        agent_id = request.data.get("agent")
        scenario_name = request.data.get("scenario")
        mode = request.data.get("mode", TestRun.Mode.TEXT)

        from zenlib.reusable_apps.multitenant import context
        tenant = context.current_tenant.get()
        try:
            agent = Agent.objects.get(id=agent_id, tenant=tenant)
        except Agent.DoesNotExist:
            return Response({"error": "Agent not found"}, status=404)

        try:
            import uuid as _uuid
            try:
                _uuid.UUID(str(scenario_name))
                scenario = Scenario.objects.get(id=scenario_name, tenant=tenant)
            except (ValueError, AttributeError):
                scenario = Scenario.objects.get(name=scenario_name, tenant=tenant)
        except Scenario.DoesNotExist:
            return Response({"error": f"Scenario '{scenario_name}' not found"}, status=404)

        run = TestRun.objects.create(agent=agent, scenario=scenario, mode=mode)
        task = run_scenario_task.delay(str(run.id), tenant.id)
        run.celery_task_id = task.id
        run.save(update_fields=["celery_task_id"])
        return Response(TestRunSerializer(run).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="results")
    def results(self, request, pk=None):
        run = self.get_object()
        try:
            return Response(TestResultSerializer(run.result).data)
        except TestResult.DoesNotExist:
            return Response({"error": "No results yet"}, status=404)

    @action(detail=False, methods=["delete"], url_path="clear")
    def clear(self, request):
        """Delete all test runs for the current tenant."""
        deleted, _ = self.get_queryset().delete()
        return Response({"deleted": deleted})


class AlertConfigViewSet(viewsets.ModelViewSet):
    serializer_class = AlertConfigSerializer

    def get_queryset(self):
        return AlertConfig.objects.filter(tenant=_tenant()).select_related("agent")


class AlertEventViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AlertEventSerializer

    def get_queryset(self):
        return AlertEvent.objects.filter(tenant=_tenant()).select_related("alert_config", "call")


def _key_hint(api_key: str) -> str:
    return f"{api_key[:4]}…{api_key[-4:]}" if len(api_key) > 8 else "…"


class ElevenLabsIntegrationView(APIView):
    """Manage the tenant's ElevenLabs API key. The raw key is write-only — GET
    returns only whether one is configured and a masked hint."""

    def get(self, request):
        cred = ElevenLabsCredential.objects.filter(tenant=_tenant()).first()
        return Response({"configured": bool(cred), "key_hint": cred.key_hint if cred else ""})

    def put(self, request):
        api_key = (request.data.get("api_key") or "").strip()
        if not api_key:
            return Response({"error": "api_key is required"}, status=status.HTTP_400_BAD_REQUEST)
        # Validate the key actually works for Conversational AI before saving.
        try:
            r = httpx.get(
                f"{ELEVENLABS_API_URL}/convai/agents",
                headers={"xi-api-key": api_key},
                timeout=15,
            )
        except httpx.HTTPError as e:
            return Response({"error": f"Could not reach ElevenLabs: {e}"},
                            status=status.HTTP_502_BAD_GATEWAY)
        if r.status_code == 401:
            return Response(
                {"error": "ElevenLabs rejected this key. It needs the convai_read permission."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if r.status_code != 200:
            return Response({"error": f"ElevenLabs error {r.status_code}"},
                            status=status.HTTP_400_BAD_REQUEST)

        hint = _key_hint(api_key)
        ElevenLabsCredential.objects.update_or_create(
            tenant=_tenant(), defaults={"api_key": api_key, "key_hint": hint},
        )
        return Response({"configured": True, "key_hint": hint})

    # Allow POST as an alias for PUT so the UI can use either verb.
    post = put
