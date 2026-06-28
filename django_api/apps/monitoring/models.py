import uuid

from django.db import models

from apps.agents.models import Agent, Call


class AlertConfig(models.Model):
    class Operator(models.TextChoices):
        GT = "gt"
        LT = "lt"
        GTE = "gte"
        LTE = "lte"
        EQ = "eq"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="alerts")
    metric_name = models.CharField(max_length=100)
    operator = models.CharField(max_length=5, choices=Operator.choices)
    threshold = models.FloatField()
    webhook_url = models.URLField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.agent.name}: {self.metric_name} {self.operator} {self.threshold}"

    def evaluate(self, value: float) -> bool:
        ops = {"gt": value > self.threshold, "lt": value < self.threshold,
               "gte": value >= self.threshold, "lte": value <= self.threshold,
               "eq": value == self.threshold}
        return ops[self.operator]


class AlertEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    alert_config = models.ForeignKey(AlertConfig, on_delete=models.CASCADE, related_name="events")
    call = models.ForeignKey(Call, on_delete=models.CASCADE, related_name="alert_events")
    triggered_at = models.DateTimeField(auto_now_add=True)
    metric_value = models.FloatField()
    payload_sent = models.JSONField(default=dict)

    class Meta:
        ordering = ["-triggered_at"]

    def __str__(self):
        return f"Alert {self.alert_config} fired for call {self.call_id}"
