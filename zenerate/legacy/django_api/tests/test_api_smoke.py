"""Smoke tests for API endpoints — routing, serializers, tenant schema."""
import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.django_db
class TestAgentAPI:
    @patch("apps.tenants.permissions.HasTenantAPIKey.has_permission", return_value=True)
    def test_agent_create_and_list(self, _, tenant_client):
        r = tenant_client.post("/api/agents/", {
            "name": "Smoke Agent",
            "system_prompt": "You are a test agent.",
        }, format="json")
        assert r.status_code == 201, r.content
        agent_id = r.data["id"]

        r2 = tenant_client.get("/api/agents/")
        assert r2.status_code == 200
        items = r2.data.get("results", r2.data) if isinstance(r2.data, dict) else r2.data
        ids = [a["id"] for a in items]
        assert agent_id in ids

    @patch("apps.tenants.permissions.HasTenantAPIKey.has_permission", return_value=True)
    @patch("apps.agents.views.AgentChat")
    def test_agent_chat(self, MockChat, _, tenant_client):
        from apps.agents.models import Agent
        agent = Agent.objects.create(name="Chat Agent", system_prompt="Help.")
        MockChat.return_value.send.return_value = {
            "response": "Hello from agent",
            "conversation_id": "conv-abc",
            "ts_ms": 150,
        }

        r = tenant_client.post(f"/api/agents/{agent.id}/chat/", {
            "message": "Hi there"
        }, format="json")
        assert r.status_code == 200
        assert r.data["response"] == "Hello from agent"
        assert r.data["conversation_id"] == "conv-abc"


@pytest.mark.django_db
class TestScenarioAPI:
    @patch("apps.tenants.permissions.HasTenantAPIKey.has_permission", return_value=True)
    def test_scenario_create_and_list(self, _, tenant_client):
        r = tenant_client.post("/api/scenarios/", {
            "name": "smoke_test",
            "persona": "A test caller",
            "yaml_content": "name: smoke_test",
        }, format="json")
        assert r.status_code == 201, r.content

        r2 = tenant_client.get("/api/scenarios/")
        assert r2.status_code == 200
        items = r2.data.get("results", r2.data) if isinstance(r2.data, dict) else r2.data
        names = [s["name"] for s in items]
        assert "smoke_test" in names
