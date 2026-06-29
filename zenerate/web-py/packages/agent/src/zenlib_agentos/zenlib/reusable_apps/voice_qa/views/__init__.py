import httpx
from celery import group as celery_group
from django.conf import settings
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from ..models import Agent, Call, Transcript, CallMetric, Scenario, TestRun, TestResult, AlertConfig, AlertEvent
from ..serializers import (
    AgentSerializer, CallSerializer, TranscriptSerializer, CallMetricSerializer,
    ScenarioSerializer, TestRunSerializer, TestResultSerializer,
    AlertConfigSerializer, AlertEventSerializer,
)
from ..services.chat import AgentChat
from ..tasks import run_scenario_task

# Module-level cache: conversation_id → AgentChat. In multi-process deployments use Redis.
_chat_sessions: dict[str, AgentChat] = {}


class AgentViewSet(viewsets.ModelViewSet):
    serializer_class = AgentSerializer

    def get_queryset(self):
        return Agent.objects.filter(status=Agent.Status.ACTIVE)

    @action(detail=True, methods=["post"], url_path="chat")
    def chat(self, request, pk=None):
        agent = self.get_object()
        message = request.data.get("message", "")
        conversation_id = request.data.get("conversation_id")
        if not message:
            return Response({"error": "message is required"}, status=status.HTTP_400_BAD_REQUEST)
        if conversation_id not in _chat_sessions:
            _chat_sessions[conversation_id] = AgentChat(agent)
        result = _chat_sessions[conversation_id].send(message, conversation_id)
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

        qs = Scenario.objects.all()
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
        return Call.objects.all().select_related("agent")

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
        return Scenario.objects.all()


class TestRunViewSet(viewsets.ModelViewSet):
    serializer_class = TestRunSerializer

    def get_queryset(self):
        return TestRun.objects.select_related("scenario", "agent").prefetch_related("result__scores")

    def create(self, request):
        agent_id = request.data.get("agent")
        scenario_name = request.data.get("scenario")
        mode = request.data.get("mode", TestRun.Mode.TEXT)

        try:
            agent = Agent.objects.get(id=agent_id)
        except Agent.DoesNotExist:
            return Response({"error": "Agent not found"}, status=404)

        try:
            scenario = Scenario.objects.get(name=scenario_name)
        except Scenario.DoesNotExist:
            return Response({"error": f"Scenario '{scenario_name}' not found"}, status=404)

        from zenlib.reusable_apps.multitenant import context
        tenant = context.current_tenant.get()
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


class AlertConfigViewSet(viewsets.ModelViewSet):
    serializer_class = AlertConfigSerializer

    def get_queryset(self):
        return AlertConfig.objects.select_related("agent")


class AlertEventViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AlertEventSerializer

    def get_queryset(self):
        return AlertEvent.objects.select_related("alert_config", "call")
