import ipaddress
import logging
import socket
from urllib.parse import urlparse

from django.utils import timezone

from ..models import Call, Transcript, CallMetric, AlertConfig, AlertEvent

logger = logging.getLogger(__name__)


def _is_safe_webhook_url(url: str) -> bool:
    """Return False for URLs that resolve to private/internal addresses (SSRF guard)."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname or ""
        blocked = {"localhost", "metadata.google.internal", "169.254.169.254"}
        if hostname.lower() in blocked:
            return False
        ip = ipaddress.ip_address(socket.gethostbyname(hostname))
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    except socket.gaierror:
        pass  # Unresolvable host is not reachable, safe to allow
    except Exception:
        return False
    return True


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
    duration_s = (call.ended_at - call.started_at).total_seconds() if call.started_at and call.ended_at else None
    latencies = [t.get("ts_ms", 0) for t in agent_turns if t.get("ts_ms")]
    avg_latency_ms = sum(latencies) / len(latencies) if latencies else 0.0
    interruptions = sum(1 for t in caller_turns if "interrupt" in t.get("quirks", []))

    metrics = {
        "duration_s": duration_s,
        "turn_count": len(agent_turns),
        "avg_latency_ms": avg_latency_ms,
        "p95_latency_ms": _percentile(latencies, 95),
        "interruption_count": interruptions,
    }
    for name, value in metrics.items():
        if value is not None:
            CallMetric.objects.update_or_create(call=call, name=name, defaults={"value": float(value)})

    _check_alerts(call, metrics)


def _percentile(values, pct):
    if not values:
        return 0.0
    sorted_v = sorted(values)
    idx = int(len(sorted_v) * pct / 100)
    return float(sorted_v[min(idx, len(sorted_v) - 1)])


def _check_alerts(call, metrics):
    for config in AlertConfig.objects.filter(agent=call.agent, is_active=True):
        value = metrics.get(config.metric_name)
        if value is not None and config.evaluate(value):
            _fire_alert(config, call, value)


def _fire_alert(config, call, value):
    import httpx
    payload = {
        "alert": config.metric_name, "operator": config.operator,
        "threshold": float(config.threshold), "actual": value,
        "agent_id": str(call.agent.id), "call_id": str(call.id),
        "triggered_at": timezone.now().isoformat(),
    }
    event = AlertEvent.objects.create(alert_config=config, call=call, metric_value=value, payload_sent=payload)
    if config.webhook_url and _is_safe_webhook_url(config.webhook_url):
        try:
            with httpx.Client(timeout=5) as client:
                client.post(config.webhook_url, json=payload)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError) as e:
            logger.error(f"Webhook failed for AlertEvent {event.id}: {e}")
    elif config.webhook_url:
        logger.warning(f"Blocked webhook to unsafe URL for AlertEvent {event.id}")
    logger.info(f"Alert fired: {config.metric_name}={value} ({config.operator} {config.threshold}) for call {call.id}")
