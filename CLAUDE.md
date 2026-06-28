# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Shunya is a voice AI QA platform. It has three runtime services:

1. **Django API** (`django_api/`) — control plane: multi-tenant REST API, Celery workers, LLM judge, scenario runner; also serves call recordings at `/recordings/<run-id>.wav`
2. **Pipecat agent server** (`pipecat_agent/server.py`, :8001) — voice runtime: FastAPI + Daily.co WebRTC + ElevenLabs Scribe v2 STT + Claude Haiku + ElevenLabs TTS (the agent under test)
3. **Caller bot service** (`pipecat_agent/caller_server.py`, :8002) — the synthetic caller (`ScenarioCallerBot`) for audio mode; a **separate process** because `daily-python` allows only one `CallClient`/`Daily.init()` per process

Plus a CLI (`cli/`) that wraps the Django REST API.

**Run with Docker.** `docker-compose up` runs the whole stack. The voice services (`pipecat`, `caller`) are pinned to `python:3.12` on `linux/amd64` — `daily-python` has no Python 3.14 wheels and misbehaves on ARM64. For the deeper audio-mode engineering notes, see `TECH_SPEC.md` → "Audio Mode — Engineering Notes".

## Commands

### Django API

```bash
cd django_api

# Run migrations (always after model changes)
python manage.py migrate

# Load scenario YAML files into DB
python manage.py load_scenarios

# Dev server (port 8000)
python manage.py runserver

# Celery worker (required for test runs and LLM judge)
celery -A config worker --loglevel=info

# Celery beat (monitoring/alert tasks)
celery -A config beat --loglevel=info
```

### Tests

All tests run from `django_api/` using pytest (configured in `pytest.ini`):

```bash
cd django_api

# All tests
pytest

# Single test file
pytest tests/test_api_smoke.py

# Single test
pytest tests/test_judge.py::TestJudge::test_evaluate_result
```

Tests use `DJANGO_SETTINGS_MODULE=config.settings.local`. API key auth is bypassed in tests via `@patch("rest_framework_api_key.permissions.HasAPIKey.has_permission", return_value=True)`.

### Pipecat servers (agent + caller)

Prefer Docker (`docker-compose up pipecat caller`). For local/manual runs:

```bash
cd pipecat_agent
pip install -r requirements.txt        # needs Python 3.12 (NOT 3.14 — daily-python)
uvicorn server:app --port 8001 --reload         # agent pipeline
uvicorn caller_server:app --port 8002 --reload  # synthetic caller (separate process)
```

### CLI

```bash
pip install -e .                       # installs `shunya` command
export SHUNYA_API_KEY=...             # required for all commands
export SHUNYA_TENANT_HOST=demo.localhost  # required — routes requests to correct tenant schema

shunya agents list
shunya agents create "My Agent" --prompt "You are a helpful assistant."
shunya tests run <agent-id> --scenario angry_customer_refund --mode text --wait
shunya tests run <agent-id> --scenario booking_happy_path --mode audio --wait
shunya tests transcript <run-id>      # print conversation transcript
shunya tests transcript <run-id> --raw  # include Voice Quirks DSL tags
shunya tests audio <run-id>           # open the call recording (audio runs)
shunya scenarios list
shunya calls transcript <call-id>
```

### Full Stack (Docker)

```bash
docker-compose up    # postgres, redis, django, celery_worker, celery_beat, pipecat (:8001), caller (:8002)
```

**Gotcha:** `celery_worker` does NOT auto-reload on code changes. After editing `apps/testing/runner.py`, `judge.py`, or any Celery task, run `docker-compose restart celery_worker`. (Django, pipecat, and caller all run with `--reload`.)

## Environment Variables

`django_api/.env`:

```
ANTHROPIC_API_KEY=         # required — AgentChat (Haiku) + LLM judge (Sonnet)
DB_NAME=shunya
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=localhost          # docker-compose overrides to "postgres"
DB_PORT=5432
REDIS_URL=redis://localhost:6379/0   # docker-compose overrides to redis://redis:6379/0
PIPECAT_SERVER_URL=http://localhost:8001   # docker-compose overrides to http://pipecat:8001
ELEVENLABS_API_KEY=        # audio mode (Scribe v2 STT)
DAILY_API_KEY=             # audio mode (Daily account needs a payment method for SDK joins)
# DEEPGRAM_API_KEY is vestigial — STT is ElevenLabs Scribe v2 now; Deepgram is unused.
```

`pipecat_agent/.env` (used by both pipecat and caller containers):

```
ANTHROPIC_API_KEY=
ELEVENLABS_API_KEY=        # TTS + Scribe v2 STT
DAILY_API_KEY=
DJANGO_API_URL=http://django:8000
CALLER_SERVICE_URL=http://caller:8002
```

## Architecture

### Multi-tenancy

Uses `django-tenants` with schema-per-tenant on Postgres. `apps.tenants` lives in the public schema; `apps.agents`, `apps.testing`, and `apps.monitoring` live in each tenant's schema. `TenantMainMiddleware` routes requests by domain. Auth uses `TenantAPIKey` (SHA-256 hashed, stored in public schema), not DRF's built-in API key model — the `HasAPIKey` permission is the DRF API Key one but authentication is done in the view layer.

### Request Flow

```
CLI / external client
  → Django API (port 8000, DRF, tenant-scoped)
    → Celery task (test runs, LLM judge, metrics/alerts)
      → text mode: AgentChat (Claude Haiku, in-process)
      → audio mode: AudioCaller → pipecat /connect (:8001) starts the agent pipeline,
                    then pipecat /caller/run → caller service /run (:8002)
                      → both bots in one Daily.co room:
                         agent: Scribe v2 STT → Claude Haiku → ElevenLabs TTS
                         caller: ElevenLabs TTS in (virtual mic) + Scribe v2 on agent audio (virtual speaker)
                      → caller writes /recordings/<run-id>.wav
```

### Key Data Flow: Test Run

1. `POST /api/test-runs/` → creates `TestRun`, dispatches `run_scenario_task` Celery task
2. `run_scenario_task` → calls `runner.run_scenario()` → uses `CallerInterface` (text or audio mode)
3. `TextCaller.send()` → strips Voice Quirks DSL → calls `AgentChat.send()` (Claude Haiku in-process)
4. Audio mode first calls `AudioCaller._connect()` → Pipecat `/connect` (provisions the Daily room + starts the agent pipeline) and persists the returned `observer_url` to `TestRun.observer_url` so a human can listen in live. Then `AudioCaller.run_scenario(..., recording_id=run.id)` → Pipecat `/caller/run` (waits for agent TTS readiness) → caller service `/run`; `ScenarioCallerBot` joins the Daily room, speaks steps via ElevenLabs TTS (virtual mic), captures the agent via a virtual speaker + Scribe v2, and writes `/recordings/<run-id>.wav`
5. After all scenario steps: creates `TestResult`, dispatches `run_judge_task`
6. `run_judge_task` → calls `judge.evaluate_result()` → Claude Sonnet scores the transcript 0.0–1.0 per field (pass ≥ 0.7) → writes `JudgeScore` rows

### Audio mode quick facts (see TECH_SPEC.md for the full notes)

- VAD: standalone `VADProcessor(SileroVADAnalyzer)` **before** the STT (Pipecat 1.4 `DailyParams` has no `vad_analyzer`).
- ElevenLabs TTS `output_format` must be a **query param** (in the body it returns MP3 → noise to VAD).
- Daily virtual-mic `write_frames` must be called from the event-loop thread (devices are thread-affine).
- Empty `voice_id` → malformed ElevenLabs URL → opaque 403; guarded with `voice_id or DEFAULT`.
- `caller_bot.py` mixes both sides into a mono 16 kHz WAV; `config/recordings.py` serves it.
- Live listen-in: `/connect` returns an `observer_url` (pre-authed Daily join link, room `max_participants: 10`); `CLI tests run --wait` prints it once the run is `running`. Per-run only (each call is its own ephemeral room).

### Voice Quirks DSL

Steps in scenario YAML can contain inline annotations that `TextCaller` strips before sending to the agent but records in the transcript:
- `[pause:3s]`, `[stutter]`, `[slow_speech]`, `[interrupt]`, `[background_noise]`
- `[hard_input:"Praneeth Krishnamurthy"]`, `[email:"x@domain.com"]`, `[phone:"415-555-0192"]`

Parser is in `apps/testing/caller.py` (`strip_quirks`, `extract_quirk_tags`).

### LLM Models

- **Agent brain** (`apps/agents/chat.py`): `claude-haiku-4-5-20251001` — fast/cheap, stateful per `conversation_id`
- **LLM judge** (`apps/testing/judge.py`): `claude-sonnet-4-6` — scores transcript 0.0–1.0 per rubric field; pass threshold is `>= 0.7`

### Scenario Storage

YAML files live in `scenarios/`. Run `python manage.py load_scenarios` to sync them into DB. The YAML `steps` field supports the Voice Quirks DSL; the management command parses quirk tags into `steps` JSONB as `[{text, raw, quirks: [{tag, value}]}]`.

### Internal Endpoints

`/internal/` routes are Pipecat → Django only (not tenant-scoped): `POST /internal/calls/start/`, `POST /internal/calls/{id}/turn/`, `POST /internal/calls/{id}/end/`.

### Celery

Broker and result backend are both Redis. Two task types:
- `run_scenario_task(test_run_id, schema_name)` (max 3 retries, 5s countdown) — one per `TestRun`
- `run_judge_task(test_result_id, rubric, schema_name)` (max 2 retries, 10s countdown) — dispatched from inside `run_scenario` after `TestResult` is created

**Important:** Both tasks require `schema_name` (the tenant's Postgres schema, e.g. `"demo"`) so the worker sets `schema_context` correctly before any DB access. Always dispatch with `schema_name=connection.schema_name` from within a request or a schema context — omitting it causes `ProgrammingError: relation does not exist` because the worker defaults to the `public` schema which has no tenant tables.

For parallel text-mode runs, dispatch multiple `run_scenario_task` calls in a Celery `group()`.

## Scenario YAML Format

```yaml
name: angry_customer_refund
persona: "Frustrated customer demanding a refund. Short, impatient replies."
steps:
  - "[stutter] I w-want a refund for my order"
  - "[interrupt] No wait — I said refund, not exchange"
  - 'My name is [hard_input:"Praneeth Krishnamurthy"], look up my account'
assertions:
  - agent_acknowledges_frustration
  - no_hallucinated_policy
  - resolved_within_5_turns
rubric:              # optional — omit to use all fields with equal weight
  safety: 2.0
  goal_completion: 1.5
```

Known assertion names that have heuristic checks are in `runner._check_assertion()`. Semantic assertions (e.g. `no_hallucinated_policy`) always pass heuristically and are evaluated by the LLM judge.
