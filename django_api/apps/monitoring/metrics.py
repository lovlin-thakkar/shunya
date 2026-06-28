import logging
from django.utils import timezone

from apps.agents.models import Call, Transcript, CallMetric
from .models import AlertConfig, AlertEvent

logger = logging.getLogger(__name__)


def compute_metrics(call_id: str):
    try:
        call = Call.objects.select_related("agent").get(id=call_id)
    except Call.DoesNotExist:
        logger.error(f"Call {call_id} not found for metric computation")
        return

    try:
        transcript = Transcript.objects.get(call=call)
    except Transcript.DoesNotExist:
        logger.warning(f"No transcript for call {call_id}")
        return

    turns = transcript.turns
    agent_turns = [t for t in turns if t["speaker"] == "agent"]
    caller_turns = [t for t in turns if t["speaker"] == "caller"]

    duration_s = None
    if call.started_at and call.ended_at:
        duration_s = (call.ended_at - call.started_at).total_seconds()

    latencies = [t.get("ts_ms", 0) for t in agent_turns if t.get("ts_ms")]
    avg_latency_ms = sum(latencies) / len(latencies) if latencies else 0.0

    interruptions = sum(
        1 for t in caller_turns if "interrupt" in t.get("quirks", [])
    )

    metrics = {
        "duration_s": duration_s,
        "turn_count": len(agent_turns),
        "avg_latency_ms": avg_latency_ms,
        "p95_latency_ms": _percentile(latencies, 95),
        "interruption_count": interruptions,
    }

    for name, value in metrics.items():
        if value is None:
            continue
        CallMetric.objects.update_or_create(
            call=call,
            name=name,
            defaults={"value": float(value)},
        )

    _check_alerts(call, metrics)


def _percentile(values: list, pct: int) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    idx = int(len(sorted_v) * pct / 100)
    return float(sorted_v[min(idx, len(sorted_v) - 1)])


def _check_alerts(call, metrics: dict):
    configs = AlertConfig.objects.filter(agent=call.agent, is_active=True)
    for config in configs:
        value = metrics.get(config.metric_name)
        if value is None:
            continue
        if config.evaluate(value):
            _fire_alert(config, call, value)


def _fire_alert(config: "AlertConfig", call, value: float):
    import httpx

    payload = {
        "alert": config.metric_name,
        "operator": config.operator,
        "threshold": float(config.threshold),
        "actual": value,
        "agent_id": str(call.agent.id),
        "call_id": str(call.id),
        "triggered_at": timezone.now().isoformat(),
    }

    event = AlertEvent.objects.create(
        alert_config=config,
        call=call,
        metric_value=value,
        payload_sent=payload,
    )

    if config.webhook_url:
        try:
            with httpx.Client(timeout=5) as client:
                client.post(config.webhook_url, json=payload)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError) as e:
            logger.error(f"Webhook failed for AlertEvent {event.id}: {e}")

    logger.info(
        f"Alert fired: {config.metric_name}={value} "
        f"({config.operator} {config.threshold}) for call {call.id}"
    )
