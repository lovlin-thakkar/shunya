from celery import shared_task


@shared_task(bind=True, max_retries=20)
def run_scenario_task(self, test_run_id: str, tenant_id: int):
    import httpx
    from django.db import IntegrityError
    from zenlib.reusable_apps.multitenant import context
    from zenlib.reusable_apps.multitenant.models import Tenant
    from ..services.runner import run_scenario
    try:
        tenant = Tenant.objects.get(id=tenant_id)
        context.current_tenant.set(tenant)
        run_scenario(test_run_id)
    except IntegrityError:
        # TestRun was deleted (e.g. "Clear All") while the task was in flight.
        # No point retrying — just discard.
        return
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (429, 502, 503):
            # 429 = pipecat at capacity; 502/503 = Daily.co overloaded.
            # Both mean "try again later" — back off linearly.
            delay = min(30 + self.request.retries * 30, 120)
            raise self.retry(exc=exc, countdown=delay)
        if self.request.retries < 3:
            raise self.retry(exc=exc, countdown=10)
        raise
    except Exception as exc:
        if self.request.retries < 3:
            raise self.retry(exc=exc, countdown=10)
        raise


@shared_task(bind=True, max_retries=2)
def run_judge_task(self, test_result_id: str, rubric: dict, tenant_id: int):
    from zenlib.reusable_apps.multitenant import context
    from zenlib.reusable_apps.multitenant.models import Tenant
    from ..services.judge import evaluate_result
    try:
        tenant = Tenant.objects.get(id=tenant_id)
        context.current_tenant.set(tenant)
        evaluate_result(test_result_id, rubric)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=10)


@shared_task
def compute_call_metrics(call_id: str, tenant_id: int):
    from zenlib.reusable_apps.multitenant import context
    from zenlib.reusable_apps.multitenant.models import Tenant
    from ..services.metrics import compute_metrics
    tenant = Tenant.objects.get(id=tenant_id)
    context.current_tenant.set(tenant)
    compute_metrics(call_id)
