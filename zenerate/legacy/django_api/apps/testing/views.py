from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Scenario, TestRun
from .serializers import ScenarioSerializer, TestRunSerializer
from .tasks import run_scenario_task


class ScenarioViewSet(viewsets.ModelViewSet):
    serializer_class = ScenarioSerializer

    def get_queryset(self):
        return Scenario.objects.all()


class TestRunViewSet(viewsets.ModelViewSet):
    serializer_class = TestRunSerializer

    def get_queryset(self):
        return TestRun.objects.select_related("scenario", "agent").prefetch_related(
            "result__scores"
        )

    def create(self, request):
        from apps.agents.models import Agent
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

        from django.db import connection
        schema = connection.schema_name
        run = TestRun.objects.create(agent=agent, scenario=scenario, mode=mode)
        task = run_scenario_task.delay(str(run.id), schema_name=schema)
        run.celery_task_id = task.id
        run.save(update_fields=["celery_task_id"])

        return Response(TestRunSerializer(run).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="results")
    def results(self, request, pk=None):
        run = self.get_object()
        from .serializers import TestResultSerializer
        from .models import TestResult
        try:
            return Response(TestResultSerializer(run.result).data)
        except TestResult.DoesNotExist:
            return Response({"error": "No results yet"}, status=404)
