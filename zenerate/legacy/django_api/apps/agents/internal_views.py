import uuid
from contextlib import contextmanager

from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from .models import Agent, Call, Transcript


@contextmanager
def _schema_ctx(schema_name: str):
    """Use schema_context when schema_name is provided, otherwise no-op."""
    if schema_name:
        from django_tenants.utils import schema_context
        with schema_context(schema_name):
            yield
    else:
        yield


class CallStartView(APIView):
    permission_classes = [AllowAny]  # internal only — not exposed externally

    def post(self, request):
        agent_id = request.data.get("agent_id")
        source = request.data.get("source", Call.Source.HUMAN)
        daily_room_url = request.data.get("daily_room_url", "")
        daily_room_name = request.data.get("daily_room_name", "")
        schema_name = request.data.get("schema_name", "")

        with _schema_ctx(schema_name):
            try:
                agent = Agent.objects.get(id=agent_id)
            except Agent.DoesNotExist:
                return Response({"error": "Agent not found"}, status=404)

            call = Call.objects.create(
                agent=agent,
                source=source,
                daily_room_url=daily_room_url,
                daily_room_name=daily_room_name,
                status=Call.Status.IN_PROGRESS,
                started_at=timezone.now(),
            )
            Transcript.objects.create(call=call, turns=[])
        return Response({"call_id": str(call.id)}, status=201)


class CallTurnView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, call_id):
        speaker = request.data.get("speaker")
        text = request.data.get("text", "")
        ts_ms = request.data.get("ts_ms", 0)
        quirks = request.data.get("quirks", [])
        schema_name = request.data.get("schema_name", "")

        with _schema_ctx(schema_name):
            try:
                transcript = Transcript.objects.get(call_id=call_id)
            except Transcript.DoesNotExist:
                return Response({"error": "Transcript not found"}, status=404)

            transcript.turns.append({"speaker": speaker, "text": text, "ts_ms": ts_ms, "quirks": quirks})
            transcript.save(update_fields=["turns"])
        return Response({"ok": True})


class CallEndView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, call_id):
        from apps.monitoring.tasks import compute_call_metrics
        schema_name = request.data.get("schema_name", "")

        with _schema_ctx(schema_name):
            try:
                call = Call.objects.get(id=call_id)
            except Call.DoesNotExist:
                return Response({"error": "Call not found"}, status=404)

            call.status = Call.Status.COMPLETED
            call.ended_at = timezone.now()
            call.save(update_fields=["status", "ended_at"])

        compute_call_metrics.delay(str(call_id), schema_name=schema_name)
        return Response({"ok": True})
