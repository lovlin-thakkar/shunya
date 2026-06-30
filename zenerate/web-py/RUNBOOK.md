# Shunya — Running Guide

Shunya is a voice AI QA platform. It tests agents using scenario-driven conversations, scores them with an LLM judge (Claude Sonnet 4.6), records audio calls, and exposes results via a REST API, CLI, and web UI.

> **Run it with Docker.** `docker-compose up` is the canonical way to run the whole stack. The voice services *must* run in containers (the Daily SDK has no Python 3.14 wheels and needs `python:3.12` on `linux/amd64`).

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│               Django API (:8000)                    │
│  Agents · Scenarios · TestRuns · Alerts · Auth      │
│  serves /recordings/<run-id>.wav                    │
└────────────┬───────────────────┬────────────────────┘
             │                   │
      ┌──────▼──────┐    ┌───────▼──────┐
      │  PostgreSQL  │    │    Redis      │
      │ (single-schema│   │ (Celery broker│
      │  RLS isolation)│   │  & results)   │
      └─────────────┘    └───────────────┘
             │
    ┌────────▼───────────┐       ┌──────────────────────┐
    │  Pipecat agent :8001 │       │   Caller bot :8002    │
    │  Daily · Scribe v2   │       │  ScenarioCallerBot    │
    │  Claude Haiku · 11Labs│ ◀───▶│  EvalAgent (remote)   │
    │  (agent under test)  │       │  (separate process)   │
    └──────────────────────┘       └──────────────────────┘
               └────────── Daily.co / ElevenLabs ConvAI ──────────┘
```

**Three test modes:**
- `text` — TextCaller injects steps directly into Claude Haiku in-process (no audio stack needed)
- `audio` — ScenarioCallerBot (separate :8002 service) joins a Daily.co room for real voice conversation with the agent (requires ElevenLabs + Daily keys)
- `remote` — EvalAgent (plain async class) connects to an ElevenLabs Conversational AI agent WebSocket, drives scenario steps; `Scorer` scores all rubric fields concurrently after each turn; EvalBridge relays audio to a Daily.co room for live listen-in

---

## 0. Docker Quickstart (recommended)

```bash
cd /Users/lovlinthakkar/PycharmProjects/Shunya/zenerate/web-py

# Put keys in apps/api/.env and services/voice/.env (see §1 Configure environment)
docker compose build
docker compose up -d        # postgres, redis, django, celery_worker, pipecat, caller, web

# One-time DB bootstrap:
docker compose exec django uv run python manage.py migrate

# Create a tenant + API key (inside the django container):
docker compose exec django uv run python manage.py shell -c "
from zenlib.reusable_apps.multitenant.models import Tenant
t = Tenant.objects.create(name='default')
print(f'Tenant ID: {t.id}')
"
docker compose exec django uv run python manage.py generate_api_key --tenant default

# Load scenarios:
docker compose exec django uv run python manage.py load_scenarios --dir /scenarios
```

Then point the CLI at it:

```bash
export SHUNYA_API_KEY=<key printed above>
export SHUNYA_BASE_URL=http://localhost:8000
shunya agents sync-elevenlabs          # sync agents from ElevenLabs account
shunya tests run <agent-id> --scenario booking_happy_path --mode text --wait
```

> **Container notes:**
> - `pipecat` (:8001) and `caller` (:8002) are `python:3.12` / `linux/amd64` images (Daily SDK requirement). They run with `--reload` and mount the source, so code edits hot-reload.
> - **The `celery_worker` container does NOT auto-reload** on code changes — after editing anything in `packages/agent/` that the worker runs (e.g. `runner.py`, `judge.py`, tasks), run `docker compose restart celery_worker`.
> - `./recordings` is a Docker volume mounted into `caller` (writes WAVs) and `django` (serves them).
> - Web UI at `http://localhost:3000`.

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.12+ | Project uses 3.12 locally |
| PostgreSQL | 14+ | Docker (included in docker-compose) |
| Redis | 7+ | Docker (included in docker-compose) |
| uv | latest | Python package manager |

---

## 1. First-Time Setup

### Clone & Install

```bash
cd /Users/lovlinthakkar/PycharmProjects/Shunya/zenerate/web-py
uv sync --all-packages
```

### Install the CLI

```bash
cd zenerate/web-py/cli
pip install -e .          # installs `shunya` command from pyproject.toml
```

### Configure environment

```bash
cp apps/api/.env.example apps/api/.env   # if example exists
cp services/voice/.env.example services/voice/.env
```

Required variables (`apps/api/.env`):

```ini
DJANGO_SECRET_KEY=dev-secret-do-not-use-in-prod
ANTHROPIC_API_KEY=sk-ant-...     # Claude Haiku (agent) + Sonnet (judge)
DB_NAME=zenapi
DB_USER=zen
DB_PASSWORD=zen
DB_HOST=localhost
DB_PORT=5432
REDIS_URL=redis://localhost:6379/0
```

Audio mode also needs (`apps/api/.env`):

```ini
ELEVENLABS_API_KEY=...           # TTS + Scribe v2 STT
DAILY_API_KEY=...                # Daily.co WebRTC
PIPECAT_SERVER_URL=http://localhost:8001
CALLER_SERVER_URL=http://localhost:8002
SERVICE_TOKEN=dev-service-token-change-me
```

Voice services need (`services/voice/.env`):

```ini
ANTHROPIC_API_KEY=...
ELEVENLABS_API_KEY=...
DAILY_API_KEY=...
DJANGO_API_URL=http://localhost:8000
CALLER_SERVICE_URL=http://localhost:8002
DJANGO_SERVICE_TOKEN=dev-service-token-change-me
DJANGO_TENANT_ID=1              # integer PK of the active tenant
```

---

## 2. Database Setup

```bash
cd apps/api

# Create the database
createdb zenapi

# Run migrations
uv run python manage.py migrate

# Create a tenant
uv run python manage.py shell -c "
from zenlib.reusable_apps.multitenant.models import Tenant
Tenant.objects.create(name='default')
"

# Generate an API key
uv run python manage.py generate_api_key --tenant default
# → exports SHUNYA_API_KEY=<raw-key>
```

---

## 3. Load Scenarios

```bash
uv run python manage.py load_scenarios --dir ../../scenarios
```

Or from Docker:

```bash
docker compose exec django uv run python manage.py load_scenarios --dir /scenarios --force
```

---

## 4. Start the Django API

```bash
cd apps/api
uv run python manage.py runserver 8000
```

The API is at `http://localhost:8000`. All endpoints require `Authorization: Api-Key <key>` header.

---

## 5. Start Celery (async task runner)

Required for test runs to execute in the background:

```bash
cd apps/api
uv run celery -A zenapi.celery worker --loglevel=info
```

---

## 6. Sync Agents from ElevenLabs

Agents are not authored locally — they are synced from each tenant's ElevenLabs account:

```bash
# First, save your ElevenLabs API key:
curl -X PUT http://localhost:8000/api/v1/integrations/elevenlabs/ \
  -H "Authorization: Api-Key <key>" \
  -H "Content-Type: application/json" \
  -d '{"api_key": "sk_..."}'

# Then sync agents:
shunya agents sync-elevenlabs
# Or: curl -X POST http://localhost:8000/api/v1/agents/sync-elevenlabs/ \
#        -H "Authorization: Api-Key <key>"

# List synced agents:
shunya agents list
```

---

## 7. REST API — Quick Reference

All requests need:
```
Authorization: Api-Key <your-key>
Content-Type: application/json
```

### Agents

```bash
# List agents
curl http://localhost:8000/api/v1/agents/ \
  -H "Authorization: Api-Key <key>"

# Chat with an agent (text mode)
curl -X POST http://localhost:8000/api/v1/agents/<agent-id>/chat/ \
  -H "Authorization: Api-Key <key>" \
  -d '{"message":"I want to book an appointment"}'
```

### Scenarios

```bash
# List loaded scenarios
curl http://localhost:8000/api/v1/scenarios/ \
  -H "Authorization: Api-Key <key>"
```

### Test Runs

```bash
# Trigger a text-mode test run
curl -X POST http://localhost:8000/api/v1/test-runs/ \
  -H "Authorization: Api-Key <key>" \
  -d '{"agent":"<agent-id>","scenario":"<scenario-id>","mode":"text"}'

# Run all scenarios in parallel against an agent
curl -X POST http://localhost:8000/api/v1/agents/<agent-id>/run-evals/ \
  -H "Authorization: Api-Key <key>"

# Check run status + transcript + judge scores
curl http://localhost:8000/api/v1/test-runs/<run-id>/ \
  -H "Authorization: Api-Key <key>"
```

### Calls

```bash
# List calls
curl http://localhost:8000/api/v1/calls/ \
  -H "Authorization: Api-Key <key>"

# Get transcript
curl http://localhost:8000/api/v1/calls/<call-id>/transcript/ \
  -H "Authorization: Api-Key <key>"

# Get call metrics
curl http://localhost:8000/api/v1/calls/<call-id>/metrics/ \
  -H "Authorization: Api-Key <key>"
```

### ElevenLabs Integration

```bash
# Check if key is configured
curl http://localhost:8000/api/v1/integrations/elevenlabs/ \
  -H "Authorization: Api-Key <key>"

# Save ElevenLabs API key
curl -X PUT http://localhost:8000/api/v1/integrations/elevenlabs/ \
  -H "Authorization: Api-Key <key>" \
  -H "Content-Type: application/json" \
  -d '{"api_key": "sk_..."}'
```

---

## 8. CLI — Shunya Control Plane

Set env vars once:

```bash
export SHUNYA_BASE_URL=http://localhost:8000
export SHUNYA_API_KEY=<your-key>
```

```bash
# Agents
shunya agents list
shunya agents show <agent-id>
shunya agents connect <agent-id>       # talk to an agent live (browser)
shunya agents chat <agent-id> "Hello"  # text-mode chat
shunya agents sync-elevenlabs          # sync from ElevenLabs account

# Scenarios
shunya scenarios list
shunya scenarios show <scenario-name>

# Test runs
shunya tests run <agent-id> --scenario angry_customer_refund --mode text
shunya tests run <agent-id> --scenario booking_happy_path --mode audio --wait
shunya tests run-evals <agent-id>      # run all scenarios in parallel
shunya tests list
shunya tests show <run-id>

# Test run transcripts
shunya tests transcript <run-id>              # clean text, no DSL annotations
shunya tests transcript <run-id> --raw        # show original [quirk] tags inline
shunya tests transcript <run-id> --no-color   # plain text (good for piping/logging)

# Audio recording (audio-mode runs)
shunya tests audio <run-id>                   # print + open the call recording link
shunya tests audio <run-id> --no-open         # just print the link

# Calls
shunya calls list
shunya calls transcript <call-id>
```

CLI errors are rendered cleanly (no traceback): missing `SHUNYA_API_KEY`, bad ID (404), unauthorized key (401/403), or unreachable server each print a one-line `Error: …` and exit non-zero.

The `--wait` flag polls until the run completes and prints judge scores inline. Judge scores are written ~10–15s after the run completes (async Celery task) — if they show "pending", run `shunya tests show <run-id>` shortly after.

---

## 9. Run Tests

```bash
cd apps/api
uv run pytest -q
```

---

## 10. Run a Scenario Inline (no Celery)

Useful for debugging or demos:

```bash
uv run python manage.py shell -c "
from zenlib.reusable_apps.multitenant import context
from zenlib.reusable_apps.multitenant.models import Tenant
from zenlib_agentos.zenlib.reusable_apps.voice_qa.models import Agent, Scenario, TestRun, JudgeScore
from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.runner import run_scenario
from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.judge import evaluate_result

t = Tenant.objects.first()
context.current_tenant.set(t)

agent = Agent.objects.first()
scenario = Scenario.objects.first()
run = TestRun.objects.create(agent=agent, scenario=scenario, mode='text')
run_scenario(str(run.id), t.id)
run.refresh_from_db()
evaluate_result(str(run.result.id), scenario.rubric, t.id)

for s in JudgeScore.objects.filter(test_result=run.result).order_by('field'):
    bar = '█' * int(s.score * 10)
    status = '✓' if s.passed else '✗'
    print(f'{status}  {s.field:<28} {bar:<10} {s.score:.2f}  {s.reasoning[:60]}')
"
```

---

## 11. Voice Agent & Audio-Fidelity Testing

Requires ElevenLabs and Daily API keys in both `apps/api/.env` and `services/voice/.env`.

### Start the voice services (prefer Docker)

```bash
docker compose up pipecat caller
```

### Or run locally

```bash
cd services/voice
pip install -r requirements.txt          # Python 3.12 only!
uvicorn server:app --port 8001 --reload  # agent pipeline
# In a separate terminal:
uvicorn caller_server:app --port 8002 --reload  # caller bot
```

### Talk to the agent live (browser)

```bash
shunya agents connect <agent-id>
# Opens a browser tab with a Daily.co room — you talk to the agent
```

### Run a scenario in audio-fidelity mode

```bash
shunya tests run <agent-id> --scenario booking_happy_path --mode audio --wait
```

### Run a scenario against a remote ElevenLabs agent

```bash
shunya tests run <agent-id> --scenario booking_happy_path --mode remote --wait
```

### Listening to a call — live or recorded

**Live (while the call is in progress):** run with `--wait` and the CLI prints a join link as soon as the run goes `running`.

```bash
shunya tests run <agent-id> --scenario booking_happy_path --mode audio --wait
# →  👁  Join to observe: https://<domain>.daily.co/<room>?t=<token>
```

**Recorded (after the call):**

```bash
shunya tests transcript <run-id>     # prints recording link for audio runs
shunya tests audio <run-id>          # prints + opens the link
# Or open directly: http://localhost:8000/recordings/<run-id>.wav
```

### Pipecat agent server endpoints (:8001)

| Endpoint | Purpose |
|---|---|
| `POST /connect` | Start agent pipeline in a new Daily room, return room URL + caller token + observer_url |
| `POST /caller/run` | Wait for agent readiness, then dispatch the caller bot (proxies to :8002) |
| `GET /health` | Liveness check |

### Caller bot service endpoints (:8002)

| Endpoint | Purpose |
|---|---|
| `POST /run` | Run `ScenarioCallerBot` through a full scenario; write WAV; return transcript |
| `POST /remote/connect` | Provision Daily room for observer access (remote EL agent test) |
| `POST /remote/run` | Drive scenario against a deployed ElevenLabs agent via `EvalAgent` |
| `GET /health` | Liveness check |

---

## 12. Web UI

The Next.js web UI runs at `http://localhost:3000` (started by `docker compose up`).

```bash
# Start manually (if not using Docker):
cd services/web
npm install
npm run dev
```

Pages:
- Agents list + detail (with ElevenLabs key gate)
- Scenarios list
- Test runs list + detail (transcript, scores, audio recording)

---

## 13. Adding a New Scenario

Create a YAML file in `scenarios/`:

```yaml
name: my_scenario
description: What this tests.
persona: >
  You are a [caller type]. [Behaviour description].
steps:
  - "Opening message"
  - "[stutter] Hard to understand message"
  - "[interrupt] Interruption mid-sentence"
  - "[hard_input:\"difficult value\"] Message with hard input"
assertions:
  - agent_acknowledges_frustration
  - no_hallucinated_policy
rubric:
  safety: 1.0
  goal_completion: 1.5
```

Load it:

```bash
uv run python manage.py load_scenarios --dir ../../scenarios --force
```

### Voice Quirks DSL Reference

| Tag | Effect |
|---|---|
| `[stutter]` | Stutter annotation; stripped in text mode |
| `[pause:3s]` | 3s pause annotation; stripped in text mode |
| `[interrupt]` | Interruption annotation |
| `[background_noise]` | Noise annotation |
| `[slow_speech]` | Slow speech annotation |
| `[hard_input:"value"]` | Hard-to-say value (spoken verbatim in audio) |
| `[email:"addr"]` | Email address (spoken verbatim in audio) |
| `[phone:"num"]` | Phone number (spoken verbatim in audio) |

---

## 14. Monitoring & Alerts

```bash
# Create an alert: fire webhook if avg latency > 500ms
curl -X POST http://localhost:8000/api/v1/agents/<agent-id>/alerts/ \
  -H "Authorization: Api-Key <key>" \
  -d '{
    "metric_name": "avg_latency_ms",
    "operator": "gt",
    "threshold": 500,
    "webhook_url": "https://hooks.slack.com/your-webhook",
    "is_active": true
  }'

# View alert events
curl http://localhost:8000/api/v1/alert-events/ \
  -H "Authorization: Api-Key <key>"
```

Supported operators: `gt`, `lt`, `gte`, `lte`, `eq`

---

## 15. Common Issues

| Error | Cause | Fix |
|---|---|---|
| `relation "voice_qa_agent" does not exist` | Migrations not run | `uv run python manage.py migrate` |
| `403 Forbidden` on API | Missing or wrong API key | Generate key: `uv run python manage.py generate_api_key` |
| Test run stuck in `queued` | Celery worker not running | Start `uv run celery -A zenapi.celery worker --loglevel=info` |
| Test run queues but empty results | RLS context not set | Ensure tasks receive `tenant_id` — already fixed in code |
| Judge scores show "pending" after `--wait` | Judge Celery task still running | Run `shunya tests show <run-id>` ~15s later |
| Code change in `runner.py`/`judge.py`/tasks has no effect | `celery_worker` container doesn't auto-reload | `docker compose restart celery_worker` |
| `pipecat` container crashes / native panic | `daily-python` on Python 3.14 or ARM64 | Containers pinned to `python:3.12` + `--platform=linux/amd64` |
| Audio run: agent never responds | Agent isn't hearing the caller | `output_format` must be query param (already fixed) |
| Audio run: 403 on TTS | `voice_id` empty | Guarded with `voice_id or DEFAULT`; set a valid voice ID |
| `/recordings/<id>.wav` 404 | No recording (text mode) | Recordings only exist for audio mode runs |
| Second concurrent remote run's audio bleeds into the first run's Daily room | Two `CallClient` instances in one process — `daily-python` only allows one | By design: second run automatically runs WS-only (no Daily relay). First room is unaffected. Check caller logs for "Another run is already using the Daily audio relay". |
| ElevenLabs "Audio duration mismatch" warning in transcript player | Gap in `user_audio_chunk` stream during agent response window | Expected: we intentionally stop sending silence during agent speech to prevent transcript overlap. The warning is cosmetic — WAV recording is the authoritative record. |
| ElevenLabs transcript player shows caller + agent voices overlapping | Old keepalive code was sending silence during agent response | Fixed: keepalive now only runs during scoring + TTS synthesis gaps. Restart `caller` service to pick up changes. |
| Scenario not found (404) when using web UI | Web UI sends UUID, old lookup was name-only | Fixed in `TestRunViewSet.create()` — tries UUID parse first, falls back to name. |
