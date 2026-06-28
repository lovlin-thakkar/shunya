from config.celery import app


@app.task(bind=True, max_retries=3)
def run_scenario_task(self, test_run_id: str, schema_name: str = "public"):
    """Runs a single scenario inside the correct tenant schema."""
    from django_tenants.utils import schema_context
    from .runner import run_scenario
    try:
        with schema_context(schema_name):
            run_scenario(test_run_id)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=5)


@app.task(bind=True, max_retries=2)
def run_judge_task(self, test_result_id: str, rubric: dict, schema_name: str = "public"):
    """Run the LLM judge on a completed TestResult inside the correct tenant schema."""
    from django_tenants.utils import schema_context
    from .judge import evaluate_result
    try:
        with schema_context(schema_name):
            evaluate_result(test_result_id, rubric)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=10)
