"""Internal API for pipecat → django communication. Requires ServiceTokenAuthentication."""
import uuid

from django.urls import path
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from ..authentication import IsServiceAccount
from ..models import Agent, Call, Transcript, TestRun
from ..tasks import compute_call_metrics


class CallStartView(APIView):
    permission_classes = [IsServiceAccount]

    def post(self, request):
        agent_id = request.data.get("agent_id")
        source = request.data.get("source", Call.Source.HUMAN)
        daily_room_url = request.data.get("daily_room_url", "")
        daily_room_name = request.data.get("daily_room_name", "")

        try:
            agent = Agent.objects.get(id=agent_id)
        except Agent.DoesNotExist:
            return Response({"error": "Agent not found"}, status=404)

        # Verify the agent belongs to the tenant the caller claims.
        claimed_tenant_id = request.headers.get("X-Tenant-Id")
        if claimed_tenant_id and str(agent.tenant_id) != str(claimed_tenant_id):
            return Response({"error": "Agent does not belong to the specified tenant"}, status=403)

        call = Call.objects.create(
            agent=agent, source=source,
            daily_room_url=daily_room_url, daily_room_name=daily_room_name,
            status=Call.Status.IN_PROGRESS, started_at=timezone.now(),
        )
        Transcript.objects.create(call=call, turns=[])
        return Response({"call_id": str(call.id)}, status=201)


class CallTurnView(APIView):
    permission_classes = [IsServiceAccount]

    def post(self, request, call_id):
        speaker = request.data.get("speaker")
        text = request.data.get("text", "")
        ts_ms = request.data.get("ts_ms", 0)
        quirks = request.data.get("quirks", [])

        try:
            transcript = Transcript.objects.get(call_id=call_id)
        except Transcript.DoesNotExist:
            return Response({"error": "Transcript not found"}, status=404)

        transcript.turns.append({"speaker": speaker, "text": text, "ts_ms": ts_ms, "quirks": quirks})
        transcript.save(update_fields=["turns"])
        return Response({"ok": True})


class CallEndView(APIView):
    permission_classes = [IsServiceAccount]

    def post(self, request, call_id):
        try:
            call = Call.objects.get(id=call_id)
        except Call.DoesNotExist:
            return Response({"error": "Call not found"}, status=404)

        call.status = Call.Status.COMPLETED
        call.ended_at = timezone.now()
        call.save(update_fields=["status", "ended_at"])

        tenant_id = request.user.tenant.id
        compute_call_metrics.delay(str(call_id), tenant_id)
        return Response({"ok": True})


class LiveScoresView(APIView):
    """Receives during-call rubric scores from the judge sub-agent (caller service)
    and stores the latest snapshot on the TestRun for the UI to poll."""
    permission_classes = [IsServiceAccount]

    def post(self, request, run_id):
        try:
            run = TestRun.objects.select_related("agent").get(id=run_id)
        except TestRun.DoesNotExist:
            return Response({"error": "TestRun not found"}, status=404)

        claimed_tenant_id = request.headers.get("X-Tenant-Id")
        if claimed_tenant_id and str(run.agent.tenant_id) != str(claimed_tenant_id):
            return Response({"error": "Run does not belong to the specified tenant"}, status=403)

        run.live_scores = {
            "turn": request.data.get("turn", 0),
            "scores": request.data.get("scores", []),
        }
        run.save(update_fields=["live_scores"])
        return Response({"ok": True})


urlpatterns = [
    path("calls/start/", CallStartView.as_view(), name="call-start"),
    path("calls/<uuid:call_id>/turn/", CallTurnView.as_view(), name="call-turn"),
    path("calls/<uuid:call_id>/end/", CallEndView.as_view(), name="call-end"),
    path("test-runs/<uuid:run_id>/live-scores/", LiveScoresView.as_view(), name="live-scores"),
]
