"""Unit tests for AlertConfig evaluation and metric computation."""
import pytest


def test_alert_config_evaluate_gt():
    from apps.monitoring.models import AlertConfig
    config = AlertConfig(metric_name="avg_latency_ms", operator="gt", threshold=500)
    assert config.evaluate(600) is True
    assert config.evaluate(400) is False


def test_alert_config_evaluate_lt():
    from apps.monitoring.models import AlertConfig
    config = AlertConfig(metric_name="csat_score", operator="lt", threshold=0.5)
    assert config.evaluate(0.3) is True
    assert config.evaluate(0.7) is False


def test_alert_config_evaluate_gte():
    from apps.monitoring.models import AlertConfig
    config = AlertConfig(metric_name="interruption_count", operator="gte", threshold=3)
    assert config.evaluate(3) is True
    assert config.evaluate(4) is True
    assert config.evaluate(2) is False


def test_alert_config_evaluate_lte():
    from apps.monitoring.models import AlertConfig
    config = AlertConfig(metric_name="turn_count", operator="lte", threshold=5)
    assert config.evaluate(5) is True
    assert config.evaluate(6) is False


def test_alert_config_evaluate_eq():
    from apps.monitoring.models import AlertConfig
    config = AlertConfig(metric_name="turn_count", operator="eq", threshold=3)
    assert config.evaluate(3) is True
    assert config.evaluate(4) is False


@pytest.mark.django_db
def test_compute_metrics_stores_callmetric():
    from unittest.mock import patch
    from django.utils import timezone
    from apps.agents.models import Agent, Call, Transcript, CallMetric
    from apps.monitoring.metrics import compute_metrics

    agent = Agent.objects.create(name="Agent", system_prompt="Be helpful.")
    call = Call.objects.create(
        agent=agent,
        source=Call.Source.TEST_TEXT,
        status=Call.Status.COMPLETED,
        started_at=timezone.now(),
        ended_at=timezone.now(),
    )
    Transcript.objects.create(call=call, turns=[
        {"speaker": "caller", "text": "Hello", "quirks": [], "ts_ms": 0},
        {"speaker": "agent", "text": "Hi", "quirks": [], "ts_ms": 220},
        {"speaker": "caller", "text": "Bye", "quirks": ["interrupt"], "ts_ms": 0},
        {"speaker": "agent", "text": "Goodbye", "quirks": [], "ts_ms": 180},
    ])

    with patch("apps.monitoring.metrics._check_alerts"):
        compute_metrics(str(call.id))

    metrics = {m.name: m.value for m in CallMetric.objects.filter(call=call)}
    assert "avg_latency_ms" in metrics
    assert metrics["avg_latency_ms"] == pytest.approx(200.0)
    assert metrics["turn_count"] == 2
    assert metrics["interruption_count"] == 1
