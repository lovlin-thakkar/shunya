from django.contrib import admin
from ..models import Agent, Call, Scenario, TestRun, TestResult, JudgeScore, AlertConfig, AlertEvent, TenantAPIKey


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "tenant", "created_at")
    list_filter = ("status",)


@admin.register(Scenario)
class ScenarioAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "created_at")


@admin.register(TestRun)
class TestRunAdmin(admin.ModelAdmin):
    list_display = ("id", "agent", "scenario", "mode", "status", "tenant", "created_at")
    list_filter = ("status", "mode")


@admin.register(TestResult)
class TestResultAdmin(admin.ModelAdmin):
    list_display = ("id", "passed", "tenant", "created_at")


@admin.register(JudgeScore)
class JudgeScoreAdmin(admin.ModelAdmin):
    list_display = ("field", "score", "passed", "tenant", "created_at")


@admin.register(AlertConfig)
class AlertConfigAdmin(admin.ModelAdmin):
    list_display = ("agent", "metric_name", "operator", "threshold", "is_active", "tenant")


@admin.register(AlertEvent)
class AlertEventAdmin(admin.ModelAdmin):
    list_display = ("alert_config", "metric_value", "tenant", "created_at")


@admin.register(TenantAPIKey)
class TenantAPIKeyAdmin(admin.ModelAdmin):
    list_display = ("key_prefix", "tenant", "created_at")
