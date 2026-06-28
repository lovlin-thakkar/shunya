import httpx
from django.conf import settings
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Agent, Call, Transcript, CallMetric
from .serializers import AgentSerializer, CallSerializer, TranscriptSerializer, CallMetricSerializer
from .chat import AgentChat

# Module-level cache so /chat/ conversations persist across HTTP requests.
# Keyed by conversation_id. In a multi-process deployment, use Redis instead.
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

        # Reuse the same AgentChat instance for the lifetime of a conversation so
        # _histories survives across HTTP requests. Keyed by conversation_id so
        # different callers don't share context.
        if conversation_id not in _chat_sessions:
            _chat_sessions[conversation_id] = AgentChat(agent)
        result = _chat_sessions[conversation_id].send(message, conversation_id)
        return Response(result)

    @action(detail=True, methods=["get"], url_path="test-runs")
    def test_runs(self, request, pk=None):
        from apps.testing.models import TestRun
        from apps.testing.serializers import TestRunSerializer
        agent = self.get_object()
        runs = TestRun.objects.filter(agent=agent)
        return Response(TestRunSerializer(runs, many=True).data)

    @action(detail=True, methods=["post"], url_path="test-runs/trigger")
    def trigger_test_run(self, request, pk=None):
        from apps.testing.models import TestRun, Scenario
        from apps.testing.serializers import TestRunSerializer
        from apps.testing.tasks import run_scenario_task

        agent = self.get_object()
        scenario_name = request.data.get("scenario")
        mode = request.data.get("mode", TestRun.Mode.TEXT)

        try:
            scenario = Scenario.objects.get(name=scenario_name)
        except Scenario.DoesNotExist:
            return Response({"error": f"Scenario '{scenario_name}' not found"}, status=404)

        from django.db import connection
        schema = connection.schema_name
        run = TestRun.objects.create(agent=agent, scenario=scenario, mode=mode)
        task = run_scenario_task.delay(str(run.id), schema_name=schema)
        run.celery_task_id = task.id
        run.save(update_fields=["celery_task_id"])

        return Response(TestRunSerializer(run).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="metrics")
    def metrics(self, request, pk=None):
        agent = self.get_object()
        metrics = CallMetric.objects.filter(call__agent=agent).select_related("call")
        return Response(CallMetricSerializer(metrics, many=True).data)

    @action(detail=True, methods=["post"], url_path="connect")
    def connect(self, request, pk=None):
        """Provision a Daily.co room, start Pipecat bot, return caller join URL."""
        agent = self.get_object()
        from django.db import connection
        try:
            r = httpx.post(
                f"{settings.PIPECAT_SERVER_URL}/connect",
                json={
                    "agent_id": str(agent.id),
                    "system_prompt": agent.system_prompt,
                    "voice_id": agent.voice_id,
                    "greeting": agent.greeting,
                    "schema_name": connection.schema_name,
                },
                timeout=10,
            )
            r.raise_for_status()
            return Response(r.json())
        except httpx.HTTPError as e:
            return Response(
                {"error": f"Voice server unavailable: {e}"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

    @action(detail=True, methods=["get", "post"], url_path="alerts")
    def alerts(self, request, pk=None):
        from apps.monitoring.models import AlertConfig
        from apps.monitoring.serializers import AlertConfigSerializer
        agent = self.get_object()
        if request.method == "GET":
            alerts = AlertConfig.objects.filter(agent=agent)
            return Response(AlertConfigSerializer(alerts, many=True).data)
        serializer = AlertConfigSerializer(data={**request.data, "agent": agent.id})
        serializer.is_valid(raise_exception=True)
        serializer.save(agent=agent)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


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
        call = self.get_object()
        metrics = CallMetric.objects.filter(call=call)
        return Response(CallMetricSerializer(metrics, many=True).data)
