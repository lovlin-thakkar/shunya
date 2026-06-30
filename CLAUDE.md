# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Layout

```
zenerate/web-py/        ← the entire active codebase
├── apps/api/           ← Django API (control plane)
├── packages/           ← shared Python packages (zenlib-mt-py, zenlib-agent-py)
├── services/voice/     ← Pipecat agent + caller bot
├── services/web/       ← Next.js web UI
├── cli/                ← shunya CLI
├── scenarios/          ← scenario YAML files
└── docker-compose.yml
```

## What This Is

Shunya is a voice AI QA platform. It has three runtime services:

1. **Django API** (`zenerate/web-py/apps/api/`) — control plane: multi-tenant REST API (RLS), Celery workers, LLM judge, scenario runner; serves call recordings at `/recordings/<run-id>.wav`
2. **Pipecat agent server** (`zenerate/web-py/services/voice/server.py`, :8001) — voice runtime: FastAPI + Daily.co WebRTC + ElevenLabs Scribe v2 STT + Claude Haiku + ElevenLabs TTS (the agent under test)
3. **Caller bot service** (`zenerate/web-py/services/voice/caller_server.py`, :8002) — the synthetic caller (`ScenarioCallerBot`) for audio mode; also runs `EvalAgent` for remote ElevenLabs agent testing; a **separate process** because `daily-python` allows only one `CallClient`/`Daily.init()` per process

Plus a CLI (`zenerate/web-py/cli/`) and a Next.js web UI (`zenerate/web-py/services/web/`).

**Run with Docker.** `docker-compose up` from `zenerate/web-py/` runs the whole stack. The voice services (`pipecat`, `caller`) are pinned to `python:3.12` on `linux/amd64` — `daily-python` has no Python 3.14 wheels and misbehaves on ARM64. For the deeper audio-mode engineering notes, see `TECH_SPEC.md` → "Audio Mode — Engineering Notes".

## Commands

### Django API (zenerate/web-py)

```bash
cd zenerate/web-py/apps/api

# Install dependencies (uv workspace)
uv sync --all-packages

# Run migrations (always after model changes)
uv run python manage.py migrate

# Load scenario YAML files into DB
uv run python manage.py load_scenarios --dir ../../scenarios

# (Agents are not authored here — they are synced from each tenant's ElevenLabs
# account via POST /api/v1/agents/sync-elevenlabs/. There is no load_agents.)

# Dev server (port 8000)
uv run python manage.py runserver

# Celery worker (required for test runs, LLM judge, and metric/alert computation)
uv run celery -A zenapi.celery worker --loglevel=info
```

### Tests

Tests run from `zenerate/web-py/apps/api/` using pytest:

```bash
cd zenerate/web-py/apps/api
uv run pytest
```

The conftest uses `tenant_a`/`tenant_b`/`in_tenant` fixtures (RLS-aware). Auth uses `api_key_headers(tenant)` for CLI-style tests or `service_headers(tenant)` for internal pipecat calls.

### Pipecat servers (agent + caller)

Prefer Docker (`docker-compose up pipecat caller` from `zenerate/web-py/`). For local/manual runs:

```bash
cd zenerate/web-py/services/voice
pip install -r requirements.txt        # needs Python 3.12 (NOT 3.14 — daily-python)
uvicorn server:app --port 8001 --reload         # agent pipeline
uvicorn caller_server:app --port 8002 --reload  # synthetic caller (separate process)
```

### CLI

```bash
pip install -e .                       # installs `shunya` command
export SHUNYA_API_KEY=...             # required for all commands
export SHUNYA_BASE_URL=http://localhost:8000  # default

shunya agents list                    # agents are synced from ElevenLabs, not created
shunya agents connect <agent-id>      # talk to an agent live (browser)
shunya tests run <agent-id> --scenario angry_customer_refund --mode text --wait
shunya tests run <agent-id> --scenario booking_happy_path --mode audio --wait
shunya tests run-evals <agent-id>     # run all scenarios in parallel
shunya tests transcript <run-id>      # print conversation transcript
shunya tests transcript <run-id> --raw  # include Voice Quirks DSL tags
shunya tests audio <run-id>           # open the call recording (audio runs)
shunya scenarios list
shunya calls transcript <call-id>
```

### Full Stack (Docker — zenerate/web-py)

```bash
cd zenerate/web-py
docker compose up    # postgres, redis, django, celery_worker, pipecat (:8001), caller (:8002), web (:3000)
```

**Gotcha:** `celery_worker` does NOT auto-reload on code changes. After editing voice_qa services or tasks, run `docker compose restart celery_worker`. (Django, pipecat, and caller all run with `--reload`.)

## Environment Variables

`zenerate/web-py/apps/api/.env` (copy from `.env.example`):

```
DJANGO_SECRET_KEY=         # required in prod
DB_NAME=zenapi
DB_USER=zen
DB_PASSWORD=zen
DB_HOST=localhost          # docker-compose overrides to "db"
DB_PORT=5432
REDIS_URL=redis://localhost:6379/0
SERVICE_TOKEN=             # shared secret for pipecat→django internal calls; must match DJANGO_SERVICE_TOKEN
ANTHROPIC_API_KEY=         # required — AgentChat (Haiku) + LLM judge (Sonnet)
ELEVENLABS_API_KEY=        # audio mode (Scribe v2 STT + TTS)
DAILY_API_KEY=             # audio mode (Daily account needs a payment method for SDK joins)
PIPECAT_SERVER_URL=http://localhost:8001   # docker-compose overrides to http://pipecat:8001
CALLER_SERVER_URL=http://localhost:8002    # docker-compose overrides to http://caller:8002
RECORDINGS_DIR=/recordings
```

`zenerate/web-py/services/voice/.env` (copy from `.env.example`):

```
ANTHROPIC_API_KEY=
ELEVENLABS_API_KEY=
DAILY_API_KEY=
DJANGO_API_URL=http://django:8000
CALLER_SERVICE_URL=http://caller:8002
DJANGO_SERVICE_TOKEN=      # must match SERVICE_TOKEN in apps/api/.env
DJANGO_TENANT_ID=1         # integer PK of the active tenant
```

## Architecture

### Multi-tenancy

Uses `zenlib-mt-py` (RLS single-schema) — all tenant data lives in the same Postgres schema, isolated by Postgres Row-Level Security policies keyed on `tenant_id`. Every model inherits `ActivityTenantBaseModel` which adds a `tenant` FK, auto-populated from the `context.current_tenant` ContextVar.

Middleware stack (order is critical):
1. `MultitenantContextMiddleware` — resolves tenant from Knox token or `X-Tenant-Id` header, sets `context.current_tenant` ContextVar
2. `TenantAPIKeyMiddleware` (Shunya-specific) — validates `Authorization: Api-Key <key>`, sets `context.current_tenant` for CLI callers
3. `MultitenantRLSMiddleware` — reads the ContextVar, runs `SET LOCAL app.current_tenant_id = <id>` on the DB connection

Auth:
- CLI → `Authorization: Api-Key <raw_key>` → `TenantAPIKeyAuthentication`
- Pipecat → `X-Service-Token` + `X-Tenant-Id` → `ServiceTokenAuthentication`
- UI → Knox token `Authorization: Token <knox> <tenant_id>`

### Request Flow

```
CLI / external client
  → Django API (port 8000, DRF, tenant-scoped)
    → Celery task (test runs, LLM judge, metrics/alerts)
      → text mode (BUILTIN agent): AgentChat (Claude Haiku, in-process)
      → audio mode (BUILTIN agent): AudioCaller → pipecat /connect (:8001) starts the agent pipeline,
                    then pipecat /caller/run → caller service /run (:8002)
                      → both bots in one Daily.co room:
                         agent: Scribe v2 STT → Claude Haiku → ElevenLabs TTS
                         caller: ElevenLabs TTS in (virtual mic) + Scribe v2 on agent audio (virtual speaker)
                      → caller writes /recordings/<run-id>.wav
      → remote mode (ELEVENLABS agent): RemoteAudioCaller → caller /remote/run (:8002)
                      → EvalAgent (plain async class) connects to ElevenLabs Conversational AI WebSocket,
                        drives scenario steps; EvalBridge relays audio to Daily room for live listen-in
                        (only ONE EvalBridge active per process — second concurrent run runs WS-only)
                      → Scorer scores all rubric fields concurrently after each agent turn (Claude Sonnet)
                        posts ONE atomic batch to Django via /internal/test-runs/{id}/live-scores/
```

### Key Data Flow: Test Run

1. `POST /api/v1/test-runs/` → creates `TestRun`, dispatches `run_scenario_task` Celery task
2. `run_scenario_task` → calls `runner.run_scenario()` → uses `CallerInterface` (text, audio, or remote mode)
3. `TextCaller.send()` → strips Voice Quirks DSL → calls `AgentChat.send()` (Claude Haiku in-process)
4. Audio mode: `AudioCaller._connect()` → Pipecat `/connect` (provisions Daily room + starts agent pipeline), persists `observer_url` to `TestRun.observer_url`. Then `AudioCaller.run_scenario(...)` → Pipecat `/caller/run` (waits for agent TTS readiness) → caller service `/run`; `ScenarioCallerBot` joins room, speaks steps via ElevenLabs TTS (virtual mic), captures agent via virtual speaker + Scribe v2, writes `/recordings/<run-id>.wav`
5. Remote mode (ELEVENLABS agents): `RemoteAudioCaller.run_scenario()` → caller service `/remote/connect` + `/remote/run`; `EvalAgent` connects to ElevenLabs Conversational AI WebSocket, drives scenario steps; `Scorer` scores all rubric fields concurrently (Claude Sonnet) after each turn and posts one atomic batch to Django. `_promote_live_scores()` in `runner.py` reads the final batch and writes permanent `JudgeScore` rows after the call.
6. After all steps: creates `TestResult`, calls `_promote_live_scores()` — for remote mode this writes `JudgeScore` rows from live scores; for text/audio mode this is a no-op (no live scores exist).

### 3-Tier Verdict System

| Tier | When | What | Who |
|------|------|------|-----|
| 1 — Heuristic Assertions | After scenario steps, before judge | Checks known assertion names (`resolved_within_5_turns`, etc.) in `runner._evaluate_assertions()` | Synchronous in `run_scenario()` |
| 2 — During-Call Live Scores | After each agent turn (remote mode only) | `Scorer` concurrently scores all rubric fields (Claude Sonnet) then posts ONE atomic batch to `POST /internal/test-runs/{id}/live-scores/`. `LiveScoresView` merges by field key. `_promote_live_scores()` writes final `JudgeScore` rows after call. | `EvalAgent` + `Scorer` (plain async classes) |
| 3 — Post-Call LLM Judge | Not currently wired in production | `judge.evaluate_result()` exists but is not called from `runner.py` or tasks (`run_judge_task` was removed). Text/audio mode results have no `JudgeScore` rows — only heuristic assertion results. Remote mode gets scores from Tier 2. | n/a (unused) |

### Agent Types

| Type | Target | CallerInterface | Voice Runtime |
|------|--------|----------------|---------------|
| `BUILTIN` | Shunya's own Pipecat pipeline (in `services/voice/pipeline.py`) | `TextCaller` (text), `AudioCaller` (audio) | Pipecat agent server (:8001) |
| `ELEVENLABS` | Remote ElevenLabs Conversational AI agent | `RemoteAudioCaller` | Caller service (:8002) — EvalAgent connects via ElevenLabs WebSocket |

### Audio mode quick facts (see TECH_SPEC.md for the full notes)

- VAD: standalone `VADProcessor(SileroVADAnalyzer)` **before** the STT (Pipecat 1.4 `DailyParams` has no `vad_analyzer`).
- ElevenLabs TTS `output_format` must be a **query param** (in the body it returns MP3 → noise to VAD).
- Daily virtual-mic `write_frames` must be called from the event-loop thread (devices are thread-affine).
- Empty `voice_id` → malformed ElevenLabs URL → opaque 403; guarded with `voice_id or DEFAULT`.
- `caller_bot.py` mixes both sides into a mono 16 kHz WAV; `config/recordings.py` serves it.
- Live listen-in: `/connect` returns an `observer_url` (pre-authed Daily join link, room `max_participants: 10`); `CLI tests run --wait` prints it once the run is `running`. Per-run only (each call is its own ephemeral room).
- **EvalAgent WAV write cursor:** ElevenLabs streams agent audio chunks as fast as the network allows (all chunks arrive in ~100ms for a 3s utterance). Using arrival time as the WAV offset collapses them into one moment. `_agent_write_cursor` anchors to wall-clock on the first chunk of each turn and advances by `len(pcm) / BYTES_PER_SEC` per chunk — preserving real-time spacing.
- **EvalBridge concurrency:** Only one `EvalBridge` (`CallClient`) may be active per caller process. Module-level `_daily_bridge_in_use` flag prevents a second concurrent run from creating a second `CallClient` (which would silence the first room and bleed audio). Second run is WS-only (ElevenLabs call still runs; just no Daily relay).
- **Keepalive strategy (ElevenLabs ConvAI):** Silence keepalive runs only during (a) scoring gap and (b) TTS synthesis — NOT during agent response. Sending keepalive during agent response records user silence simultaneous with agent audio, creating overlap in ElevenLabs' transcript player.

### Voice Quirks DSL

Steps in scenario YAML can contain inline annotations that `TextCaller` strips before sending to the agent but records in the transcript:
- `[pause:3s]`, `[stutter]`, `[slow_speech]`, `[interrupt]`, `[background_noise]`
- `[hard_input:"Praneeth Krishnamurthy"]`, `[email:"x@domain.com"]`, `[phone:"415-555-0192"]`

Parser is in `packages/agent/src/zenlib_agentos/zenlib/reusable_apps/voice_qa/services/caller.py` (`strip_quirks`, `extract_quirk_tags`).

### LLM Models

- **Agent brain** (`packages/agent/.../voice_qa/services/chat.py`): `claude-haiku-4-5-20251001` — fast/cheap, stateful per `conversation_id`
- **Live scorer** (`services/voice/eval_agent.py` → `Scorer`): `claude-sonnet-4-6` — scores all rubric fields concurrently after each agent turn (remote mode); one atomic POST per turn
- **LLM judge** (`packages/agent/.../voice_qa/services/judge.py`): `claude-sonnet-4-6` — text/audio mode only; scores full transcript 0.0–1.0 per rubric field; pass threshold `>= 0.7`

### Scenario Storage

YAML files live in `scenarios/`. Run `python manage.py load_scenarios` to sync them into DB. The YAML `steps` field supports the Voice Quirks DSL; the management command parses quirk tags into `steps` JSONB as `[{text, raw, quirks: [{tag, value}]}]`.

### Internal Endpoints

`/internal/` routes are Pipecat → Django only (not tenant-scoped): `POST /internal/calls/start/`, `POST /internal/calls/{id}/turn/`, `POST /internal/calls/{id}/end/`, `POST /internal/test-runs/{id}/live-scores/`.

### Celery

Broker and result backend are both Redis. Celery app is `zenapi.celery`. Task types:
- `run_scenario_task(test_run_id, tenant_id)` (max 3 retries) — one per `TestRun`
- `compute_call_metrics(call_id, tenant_id)` — dispatched from internal `/calls/{id}/end/`

> **`run_judge_task` is gone.** Remote mode uses live scores promoted by `_promote_live_scores()` in `runner.py` (synchronous, after `TestResult` is created). Text/audio mode calls `judge.evaluate_result()` directly from `runner.py` — no separate Celery task needed.

**Important:** All tasks take `tenant_id` (integer PK) and call `context.current_tenant.set(tenant)` before any ORM access. This sets the RLS context for the worker. Always dispatch with `tenant.id` from within a tenant-scoped request.

For parallel text-mode runs, dispatch multiple `run_scenario_task` calls in a Celery `group()`. The `run-evals` endpoint dispatches one task per scenario as a Celery `group()`.

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
