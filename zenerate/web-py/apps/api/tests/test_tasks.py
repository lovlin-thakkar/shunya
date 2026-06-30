"""Tests for the Celery task wrappers — tenant context + service dispatch + retries."""
from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from celery.exceptions import Retry
from django.db import IntegrityError

pytestmark = pytest.mark.django_db

TASKS = "zenlib_agentos.zenlib.reusable_apps.voice_qa"


def _http_error(status: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "http://pipecat/connect")
    return httpx.HTTPStatusError("boom", request=req, response=httpx.Response(status, request=req))


# --------------------------------------------------------------------------- run_scenario_task

def test_run_scenario_task_dispatches_with_tenant(tenant_a):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.tasks import run_scenario_task
    from zenlib.reusable_apps.multitenant import context

    seen = {}

    def fake_run(run_id):
        seen["run_id"] = run_id
        seen["tenant"] = context.current_tenant.get()

    with patch(f"{TASKS}.services.runner.run_scenario", side_effect=fake_run):
        result = run_scenario_task.apply(args=["run-123", tenant_a.id])

    assert result.successful()
    assert seen["run_id"] == "run-123"
    assert seen["tenant"].id == tenant_a.id


def test_run_scenario_task_discards_on_integrityerror(tenant_a):
    """TestRun deleted mid-flight (Clear All) → discard, no retry, no raise."""
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.tasks import run_scenario_task
    with patch(f"{TASKS}.services.runner.run_scenario", side_effect=IntegrityError("gone")):
        result = run_scenario_task.apply(args=["run-123", tenant_a.id])
    assert result.successful()


def test_run_scenario_task_retries_on_transient_http(tenant_a):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.tasks import run_scenario_task
    with patch(f"{TASKS}.services.runner.run_scenario", side_effect=_http_error(503)), \
         patch.object(run_scenario_task, "retry", side_effect=Retry()) as mock_retry:
        run_scenario_task.apply(args=["run-123", tenant_a.id])
    assert mock_retry.called
    # transient errors back off linearly (>= 30s)
    assert mock_retry.call_args.kwargs.get("countdown", 0) >= 30


def test_run_scenario_task_retries_on_unexpected_error(tenant_a):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.tasks import run_scenario_task
    with patch(f"{TASKS}.services.runner.run_scenario", side_effect=RuntimeError("oops")), \
         patch.object(run_scenario_task, "retry", side_effect=Retry()) as mock_retry:
        run_scenario_task.apply(args=["run-123", tenant_a.id])
    assert mock_retry.called


# --------------------------------------------------------------------------- compute_call_metrics

def test_compute_call_metrics_dispatches(tenant_a):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.tasks import compute_call_metrics
    with patch(f"{TASKS}.services.metrics.compute_metrics") as mock_metrics:
        result = compute_call_metrics.apply(args=["call-1", tenant_a.id])
    assert result.successful()
    mock_metrics.assert_called_once_with("call-1")
