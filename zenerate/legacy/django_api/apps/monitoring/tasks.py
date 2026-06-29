from config.celery import app


@app.task
def compute_call_metrics(call_id: str, schema_name: str = ""):
    """Compute and store CallMetric after a call ends."""
    if schema_name:
        from django_tenants.utils import schema_context
        with schema_context(schema_name):
            from .metrics import compute_metrics
            compute_metrics(call_id)
    else:
        from .metrics import compute_metrics
        compute_metrics(call_id)
