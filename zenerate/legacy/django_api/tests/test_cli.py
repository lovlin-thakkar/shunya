"""
CLI unit tests — all HTTP is mocked via patch on cli.client.get / cli.client.post
so these run without a live server and are counted in coverage.
"""
import pytest
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner
from cli.main import app

runner = CliRunner()

FAKE_AGENT_ID = "aaaaaaaa-0000-0000-0000-000000000001"
FAKE_RUN_ID   = "bbbbbbbb-0000-0000-0000-000000000002"


# ── agents ───────────────────────────────────────────────────────────────────

class TestAgentsCLI:
    def test_agents_list_empty(self):
        with patch("cli.client.get", return_value=[]) as mock_get:
            result = runner.invoke(app, ["agents", "list"])
        assert result.exit_code == 0
        mock_get.assert_called_once_with("/api/agents/")

    def test_agents_list_with_results(self):
        agents = [
            {"id": FAKE_AGENT_ID, "name": "My Agent", "created_at": "2026-01-01T00:00:00Z"},
        ]
        with patch("cli.client.get", return_value={"results": agents}):
            result = runner.invoke(app, ["agents", "list"])
        assert result.exit_code == 0
        assert "My Agent" in result.output

    def test_agents_create(self):
        fake = {"id": FAKE_AGENT_ID, "name": "New Agent", "system_prompt": "Help."}
        with patch("cli.client.post", return_value=fake) as mock_post:
            result = runner.invoke(app, ["agents", "create", "New Agent", "--prompt", "Help."])
        assert result.exit_code == 0
        assert "New Agent" in result.output
        mock_post.assert_called_once_with("/api/agents/", {"name": "New Agent", "system_prompt": "Help."})

    def test_agents_show(self):
        fake = {"id": FAKE_AGENT_ID, "name": "Existing Agent", "system_prompt": "Go."}
        with patch("cli.client.get", return_value=fake):
            result = runner.invoke(app, ["agents", "show", FAKE_AGENT_ID])
        assert result.exit_code == 0

    def test_agents_chat(self):
        fake = {"response": "Hi!", "conversation_id": "conv-1", "ts_ms": 42}
        with patch("cli.client.post", return_value=fake) as mock_post:
            result = runner.invoke(app, ["agents", "chat", FAKE_AGENT_ID, "Hello"])
        assert result.exit_code == 0
        assert "Hi!" in result.output
        mock_post.assert_called_once_with(
            f"/api/agents/{FAKE_AGENT_ID}/chat/", {"message": "Hello"}
        )

    def test_agents_chat_with_conversation(self):
        fake = {"response": "Again!", "conversation_id": "conv-1", "ts_ms": 10}
        with patch("cli.client.post", return_value=fake) as mock_post:
            result = runner.invoke(
                app, ["agents", "chat", FAKE_AGENT_ID, "Hi again", "--conv", "conv-1"]
            )
        assert result.exit_code == 0
        mock_post.assert_called_once_with(
            f"/api/agents/{FAKE_AGENT_ID}/chat/",
            {"message": "Hi again", "conversation_id": "conv-1"},
        )


# ── scenarios ────────────────────────────────────────────────────────────────

class TestScenariosCLI:
    def test_scenarios_list(self):
        scenarios = [{"name": "angry_customer", "description": "Angry", "steps": [1, 2]}]
        with patch("cli.client.get", return_value={"results": scenarios}):
            result = runner.invoke(app, ["scenarios", "list"])
        assert result.exit_code == 0
        assert "angry_customer" in result.output

    def test_scenarios_show_found(self):
        scenarios = [
            {"name": "angry_customer", "yaml_content": "name: angry_customer\n", "steps": []}
        ]
        with patch("cli.client.get", return_value={"results": scenarios}):
            result = runner.invoke(app, ["scenarios", "show", "angry_customer"])
        assert result.exit_code == 0
        assert "angry_customer" in result.output

    def test_scenarios_show_not_found(self):
        with patch("cli.client.get", return_value={"results": []}):
            result = runner.invoke(app, ["scenarios", "show", "nonexistent"])
        assert result.exit_code == 1


# ── tests ─────────────────────────────────────────────────────────────────────

class TestTestsCLI:
    def test_tests_run_no_wait(self):
        fake_run = {"id": FAKE_RUN_ID, "status": "queued"}
        with patch("cli.client.post", return_value=fake_run) as mock_post:
            result = runner.invoke(
                app, ["tests", "run", FAKE_AGENT_ID, "--scenario", "happy_path", "--mode", "text"]
            )
        assert result.exit_code == 0
        assert FAKE_RUN_ID in result.output
        mock_post.assert_called_once_with(
            "/api/test-runs/",
            {"agent": FAKE_AGENT_ID, "scenario": "happy_path", "mode": "text"},
        )

    def test_tests_run_with_wait_completed(self):
        fake_run = {"id": FAKE_RUN_ID, "status": "queued"}
        completed = {
            "id": FAKE_RUN_ID,
            "status": "completed",
            "mode": "text",
            "result": {
                "passed": True,
                "transcript": [],
                "scores": [
                    {"field": "safety", "score": 0.9, "passed": True, "reasoning": "Safe"},
                ],
            },
        }
        with patch("cli.client.post", return_value=fake_run), \
             patch("cli.client.get", return_value=completed), \
             patch("time.sleep"):
            result = runner.invoke(
                app, ["tests", "run", FAKE_AGENT_ID, "--scenario", "happy", "--wait"]
            )
        assert result.exit_code == 0
        assert "completed" in result.output

    def test_tests_run_with_wait_failed(self):
        fake_run = {"id": FAKE_RUN_ID, "status": "queued"}
        failed = {
            "id": FAKE_RUN_ID,
            "status": "failed",
            "mode": "text",
            "result": {
                "passed": False,
                "transcript": [],
                "scores": [],
            },
        }
        with patch("cli.client.post", return_value=fake_run), \
             patch("cli.client.get", return_value=failed), \
             patch("time.sleep"):
            result = runner.invoke(
                app, ["tests", "run", FAKE_AGENT_ID, "--scenario", "bad", "--wait"]
            )
        assert result.exit_code == 0
        assert "failed" in result.output

    def test_tests_list(self):
        runs = [
            {
                "id": FAKE_RUN_ID,
                "agent": FAKE_AGENT_ID,
                "scenario": "happy_path",
                "mode": "text",
                "status": "completed",
                "result": {"passed": True},
            }
        ]
        with patch("cli.client.get", return_value={"results": runs}):
            result = runner.invoke(app, ["tests", "list"])
        assert result.exit_code == 0
        assert FAKE_RUN_ID in result.output

    def test_tests_show(self):
        run = {
            "id": FAKE_RUN_ID,
            "status": "completed",
            "mode": "text",
            "result": {"passed": True, "scores": []},
        }
        with patch("cli.client.get", return_value=run):
            result = runner.invoke(app, ["tests", "show", FAKE_RUN_ID])
        assert result.exit_code == 0

    def test_tests_transcript_no_result(self):
        with patch("cli.client.get", return_value={"id": FAKE_RUN_ID, "result": None}):
            result = runner.invoke(app, ["tests", "transcript", FAKE_RUN_ID])
        assert result.exit_code == 1

    def test_tests_transcript_with_turns(self):
        run = {
            "id": FAKE_RUN_ID,
            "status": "completed",
            "mode": "text",
            "result": {
                "passed": True,
                "transcript": [
                    {"speaker": "caller", "text": "Hello there", "raw": "Hello there", "quirks": [], "ts_ms": 0},
                    {"speaker": "agent", "text": "Hi, how can I help?", "raw": "Hi, how can I help?", "quirks": [], "ts_ms": 150},
                ],
            },
        }
        with patch("cli.client.get", return_value=run):
            result = runner.invoke(app, ["tests", "transcript", FAKE_RUN_ID])
        assert result.exit_code == 0
        assert "Hello there" in result.output
        assert "Hi, how can I help?" in result.output

    def test_tests_transcript_raw_flag(self):
        run = {
            "id": FAKE_RUN_ID,
            "status": "completed",
            "mode": "text",
            "result": {
                "passed": True,
                "transcript": [
                    {
                        "speaker": "caller",
                        "text": "I want a refund",
                        "raw": "[stutter] I w-want a refund",
                        "quirks": ["stutter"],
                        "ts_ms": 0,
                    },
                ],
            },
        }
        with patch("cli.client.get", return_value=run):
            result = runner.invoke(app, ["tests", "transcript", FAKE_RUN_ID, "--raw"])
        assert result.exit_code == 0
        assert "w-want" in result.output

    def test_tests_transcript_audio_run_shows_recording_url(self):
        run = {
            "id": FAKE_RUN_ID,
            "status": "completed",
            "mode": "audio",
            "result": {
                "passed": True,
                "transcript": [
                    {"speaker": "caller", "text": "Hi", "raw": "Hi", "quirks": [], "ts_ms": 0},
                ],
            },
        }
        with patch("cli.client.get", return_value=run):
            result = runner.invoke(app, ["tests", "transcript", FAKE_RUN_ID])
        assert result.exit_code == 0
        assert "recordings" in result.output


# ── calls ─────────────────────────────────────────────────────────────────────

class TestCallsCLI:
    def test_calls_list(self):
        calls = [
            {
                "id": "cccccccc-0000-0000-0000-000000000003",
                "agent": FAKE_AGENT_ID,
                "source": "test",
                "status": "completed",
                "started_at": "2026-01-01T00:00:00Z",
            }
        ]
        with patch("cli.client.get", return_value={"results": calls}):
            result = runner.invoke(app, ["calls", "list"])
        assert result.exit_code == 0

    def test_calls_transcript(self):
        data = {
            "turns": [
                {"speaker": "caller", "text": "Hi", "quirks": []},
                {"speaker": "agent", "text": "Hello", "quirks": []},
            ]
        }
        with patch("cli.client.get", return_value=data):
            result = runner.invoke(app, ["calls", "transcript", "call-id-123"])
        assert result.exit_code == 0
        assert "Hi" in result.output

    def test_calls_metrics(self):
        data = [{"name": "latency_p50", "value": 0.312}]
        with patch("cli.client.get", return_value=data):
            result = runner.invoke(app, ["calls", "metrics", "call-id-123"])
        assert result.exit_code == 0
        assert "latency_p50" in result.output


# ── client error handling ─────────────────────────────────────────────────────

class TestClientErrors:
    def test_missing_api_key_raises_clean_error(self):
        import cli.client as c
        original = c.API_KEY
        c.API_KEY = ""
        try:
            with pytest.raises(c.ShunyaError, match="SHUNYA_API_KEY is not set"):
                c._headers()
        finally:
            c.API_KEY = original

    def test_404_raises_shunya_error(self):
        import httpx
        import cli.client as c
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.is_success = False
        mock_resp.status_code = 404
        mock_resp.json.return_value = {}
        mock_resp.text = ""
        mock_resp.request = MagicMock()
        mock_resp.request.url.path = "/api/agents/bad-id/"
        with pytest.raises(c.ShunyaError, match="Not found"):
            c._raise_for_status(mock_resp)

    def test_401_raises_shunya_error(self):
        import httpx
        import cli.client as c
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.is_success = False
        mock_resp.status_code = 401
        mock_resp.json.return_value = {}
        mock_resp.text = ""
        mock_resp.request = MagicMock()
        mock_resp.request.url.path = "/api/agents/"
        with pytest.raises(c.ShunyaError, match="Unauthorized"):
            c._raise_for_status(mock_resp)
