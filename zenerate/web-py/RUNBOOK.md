# Shunya — Running Guide

Shunya is a simplified Cekura-style QA platform for voice AI agents. It tests agents using scenario-driven conversations, scores them with an LLM judge (Claude Sonnet 4.6), records audio calls, and exposes results via a REST API and CLI.

> **Run it with Docker.** `docker-compose up` is the canonical way to run the whole stack. The voice services *must* run in containers (the Daily SDK has no Python 3.14 wheels and needs `python:3.12` on `linux/amd64`). The local-Python instructions in §1–§7 still work for the Django/CLI side, but the **Docker quickstart below is recommended**.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                   Django API (:8000)                │
│  Agents · Scenarios · TestRuns · Monitoring · Auth  │
│  serves /recordings/<run-id>.wav                    │
└────────────┬───────────────────┬────────────────────┘
             │                   │
      ┌──────▼──────┐    ┌───────▼──────┐
      │  PostgreSQL  │    │    Redis      │
      │ (multi-tenant│    │ (Celery broker│
      │   schemas)   │    │  & results)   │
      └─────────────┘    └───────────────┘
             │
   ┌─────────▼───────────┐        ┌──────────────────────┐
   │  Pipecat agent :8001 │◀──────▶│   Caller bot :8002    │
   │  Daily · Scribe v2   │ /caller│  ScenarioCallerBot    │
   │  Claude Haiku · 11Labs│  /run │  (joins same room,    │
   │  (agent under test)  │        │   records the call)   │
   └──────────────────────┘        └──────────────────────┘
              └───────── Daily.co room (bot ↔ bot) ─────────┘
```

**Two test modes:**
- `text` — TextCaller injects steps directly into Claude Haiku in-process (no audio stack needed)
- `audio` — ScenarioCallerBot (separate :8002 service) joins a Daily.co room and has a real voice conversation with the agent (requires ElevenLabs + Daily keys; **no Deepgram** — STT is ElevenLabs Scribe v2). Every audio run is recorded to a WAV.

---

## 0. Docker Quickstart (recommended)

```bash
cd /Users/lovlinthakkar/PycharmProjects/Shunya

# Put keys in apps/api/.env and services/voice/.env (see §1 Configure environment)
docker-compose build
docker-compose up -d        # postgres, redis, django, celery_worker, pipecat, caller

# One-time DB + tenant + scenario bootstrap (inside the django container):
docker-compose exec django python manage.py migrate_schemas --shared
docker-compose exec django python manage.py shell -c "
from apps.tenants.models import Tenant, Domain
from rest_framework_api_key.models import APIKey
for sn, dom, nm in [('public','localhost','Public'), ('demo','demo.localhost','Demo Org')]:
    if not Tenant.objects.filter(schema_name=sn).exists():
        t=Tenant(schema_name=sn, name=nm); t.save()
        Domain.objects.create(domain=dom, tenant=t, is_primary=True)
_, key = APIKey.objects.create_key(name='demo-key'); print('API Key:', key)
"
docker-compose exec django python manage.py tenant_command load_scenarios --schema=demo --dir /scenarios
```

Then point the CLI at it:

```bash
export SHUNYA_API_URL=http://localhost:8000
export SHUNYA_API_KEY=<key printed above>
export SHUNYA_TENANT_HOST=demo.localhost
shunya agents create "Support Bot" --prompt "You are a helpful dental clinic assistant."
shunya tests run <agent-id> --scenario booking_happy_path --mode audio --wait
```

> **Container notes:**
> - `pipecat` (:8001) and `caller` (:8002) are `python:3.12` / `linux/amd64` images (Daily SDK requirement). They run with `--reload` and mount the source, so code edits hot-reload.
> - **The `celery_worker` container does NOT auto-reload** on code changes — after editing anything under `django_api/apps/` that the worker runs (e.g. `runner.py`, `judge.py`, tasks), run `docker-compose restart celery_worker`.
> - `./recordings` is bind-mounted into `caller` (writes WAVs) and `django` (serves them) — recordings also appear on your host in `./recordings/`.

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.12+ | Project uses 3.14 locally |
| PostgreSQL | 14+ | Local Homebrew or Docker |
| Redis | 7+ | Via Docker (included in docker-compose) |
| Docker Desktop | any | For Redis; optional for Postgres |

---

## 1. First-Time Setup

### Clone & create virtual environment

```bash
cd /Users/lovlinthakkar/PycharmProjects/Shunya
python3 -m venv .venv
source .venv/bin/activate
pip install -r django_api/requirements.txt
```

### Install the CLI

```bash
pip install -e .          # installs `shunya` command from setup.py
```

### Configure environment

```bash
cp django_api/.env.example django_api/.env   # if example exists
# or edit django_api/.env directly
```

Required variables:

```ini
ANTHROPIC_API_KEY=sk-ant-...     # Claude Haiku (agent) + Sonnet (judge)
DB_NAME=shunya
DB_USER=<your-postgres-user>     # e.g. lovlinthakkar (macOS default)
DB_PASSWORD=                     # blank for local trust auth
DB_HOST=localhost
DB_PORT=5432
REDIS_URL=redis://localhost:6379/0
```

Optional (audio-fidelity mode only):

```ini
ELEVENLABS_API_KEY=...   # TTS (caller + agent) and Scribe v2 STT (agent transcription)
DAILY_API_KEY=...
PIPECAT_SERVER_URL=http://localhost:8001
```

---

## 2. Start Infrastructure

### Option A — Docker (Redis only, local Postgres)

```bash
# From project root
docker-compose up -d redis
```

### Option B — Docker (Postgres + Redis)

```bash
docker-compose up -d postgres redis
# Then set DB_USER=postgres, DB_PASSWORD=postgres in .env
```

### Verify

```bash
docker-compose ps          # both containers should show "Up"
redis-cli ping             # should return PONG
psql -U $DB_USER -d postgres -c "SELECT 1;"
```

---

## 3. Database Setup

Run once on a fresh install:

```bash
cd django_api

# Create the database (skip if already exists)
psql -U $DB_USER -d postgres -c "CREATE DATABASE shunya;"

# Migrate shared schema (auth, tenants, api_keys)
python manage.py migrate_schemas --shared

# Create the public tenant (required by django-tenants)
python manage.py shell -c "
from apps.tenants.models import Tenant, Domain
t = Tenant(schema_name='public', name='Public')
t.save()
Domain.objects.create(domain='localhost', tenant=t, is_primary=True)
print('Public tenant created')
"
```

---

## 4. Create a Tenant

Each organisation gets its own Postgres schema and API key:

```bash
python manage.py shell -c "
from apps.tenants.models import Tenant, Domain, TenantAPIKey

t = Tenant(schema_name='demo', name='Demo Org')
t.save()                   # triggers CREATE SCHEMA demo + migrate
Domain.objects.create(domain='demo.localhost', tenant=t, is_primary=True)

key_obj, raw_key = TenantAPIKey.generate(t)
print('API Key:', raw_key)
"
```

Save the printed API key — it is shown only once.

To generate a DRF API key (used for HTTP auth in the current setup):

```bash
python manage.py shell -c "
from rest_framework_api_key.models import APIKey
_, key = APIKey.objects.create_key(name='demo-key')
print('API Key:', key)
"
```

---

## 5. Load Scenarios

```bash
# Load bundled scenarios from /scenarios directory
python manage.py tenant_command load_scenarios --schema=demo \
  --dir /path/to/Shunya/scenarios

# Force-update existing scenarios
python manage.py tenant_command load_scenarios --schema=demo \
  --dir /path/to/Shunya/scenarios --force
```

Bundled scenarios:
- `booking_happy_path` — cooperative caller booking an appointment
- `angry_customer_refund` — frustrated caller demanding a refund; tests interruption handling
- `edge_case_gibberish` — poor connection, unclear input; tests resilience

---

## 6. Start the Django API

```bash
cd django_api
python manage.py runserver 8000
```

The API is now at `http://localhost:8000`. All endpoints require the `Host` header to route to the correct tenant schema and an `Authorization: Api-Key <key>` header.

---

## 7. Start Celery (async task runner)

Required for test runs to execute in the background:

```bash
cd django_api
celery -A config worker --loglevel=info
```

---

## 8. REST API — Quick Reference

All requests need:
```
Host: demo.localhost
Authorization: Api-Key <your-key>
Content-Type: application/json
```

### Agents

```bash
# Create an agent
curl -X POST http://localhost:8000/api/agents/ \
  -H "Host: demo.localhost" \
  -H "Authorization: Api-Key <key>" \
  -d '{"name":"Support Bot","system_prompt":"You are a helpful dental clinic assistant."}'

# List agents
curl http://localhost:8000/api/agents/ \
  -H "Host: demo.localhost" \
  -H "Authorization: Api-Key <key>"

# Chat with an agent
curl -X POST http://localhost:8000/api/agents/<agent-id>/chat/ \
  -H "Host: demo.localhost" \
  -H "Authorization: Api-Key <key>" \
  -d '{"message":"I want to book an appointment"}'
```

### Scenarios

```bash
# List loaded scenarios
curl http://localhost:8000/api/scenarios/ \
  -H "Host: demo.localhost" \
  -H "Authorization: Api-Key <key>"
```

### Test Runs

```bash
# Trigger a text-mode test run
curl -X POST http://localhost:8000/api/test-runs/ \
  -H "Host: demo.localhost" \
  -H "Authorization: Api-Key <key>" \
  -d '{"agent":"<agent-id>","scenario":"booking_happy_path","mode":"text"}'

# Check run status + transcript + judge scores
curl http://localhost:8000/api/test-runs/<run-id>/ \
  -H "Host: demo.localhost" \
  -H "Authorization: Api-Key <key>"
# Response includes: status, result.passed, result.transcript[], result.scores[]
```

### Calls

```bash
# List calls
curl http://localhost:8000/api/calls/ \
  -H "Host: demo.localhost" \
  -H "Authorization: Api-Key <key>"

# Get transcript
curl http://localhost:8000/api/calls/<call-id>/transcript/ \
  -H "Host: demo.localhost" \
  -H "Authorization: Api-Key <key>"

# Get call metrics
curl http://localhost:8000/api/calls/<call-id>/metrics/ \
  -H "Host: demo.localhost" \
  -H "Authorization: Api-Key <key>"
```

---

## 9. CLI — Shunya Control Plane

Set env vars once:

```bash
export SHUNYA_API_URL=http://localhost:8000
export SHUNYA_API_KEY=<your-key>
export SHUNYA_TENANT_HOST=demo.localhost   # routes CLI requests to the right tenant schema
```

```bash
# Agents
shunya agents list
shunya agents create "My Agent" --prompt "You are a helpful assistant."
shunya agents show <agent-id>
shunya agents chat <agent-id> "Hello, I need help"

# Scenarios
shunya scenarios list
shunya scenarios show booking_happy_path

# Test runs
shunya tests run <agent-id> --scenario angry_customer_refund --mode text
shunya tests run <agent-id> --scenario booking_happy_path --mode text --wait
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
shunya calls metrics <call-id>
```

CLI errors are rendered cleanly (no traceback): a missing `SHUNYA_API_KEY`, a bad ID (404), an unauthorized key (401/403), or an unreachable server each print a one-line `Error: …` and exit non-zero.

The `--wait` flag polls until the run completes and prints judge scores inline. Judge scores are written ~10–15s after the run completes (async Celery task) — if they show "pending", run `shunya tests show <run-id>` shortly after.

---

## 10. Run Tests

```bash
cd django_api

# Unit tests only (no database needed)
pytest tests/test_caller.py tests/test_monitoring.py tests/test_judge.py \
  -k "not django_db" -v

# All tests (requires running Postgres)
pytest tests/ -v
```

---

## 11. Run a Scenario Inline (no Celery)

Useful for debugging or demos:

```bash
python manage.py shell -c "
import django_tenants.utils as tu

with tu.schema_context('demo'):
    from apps.agents.models import Agent
    from apps.testing.models import TestRun, Scenario, JudgeScore
    from apps.testing.runner import run_scenario
    from apps.testing.judge import evaluate_result

    agent = Agent.objects.first()
    scenario = Scenario.objects.get(name='angry_customer_refund')
    run = TestRun.objects.create(agent=agent, scenario=scenario, mode='text')

    run_scenario(str(run.id))
    run.refresh_from_db()

    evaluate_result(str(run.result.id), scenario.rubric)

    for s in JudgeScore.objects.filter(test_result=run.result).order_by('field'):
        bar = '█' * int(s.score * 10)
        status = '✓' if s.passed else '✗'
        print(f'{status}  {s.field:<28} {bar:<10} {s.score:.2f}  {s.reasoning[:60]}')
"
```

---

## 12. Voice Agent & Audio-Fidelity Testing

Requires ElevenLabs and Daily API keys in `services/voice/.env` (or environment).
ElevenLabs handles both TTS (caller speaking) and STT via Scribe v2 (transcribing agent) — no Deepgram needed.

```bash
export DAILY_API_KEY=...
export ELEVENLABS_API_KEY=...
export ANTHROPIC_API_KEY=...
```

### Start the Pipecat server

```bash
cd services/voice
pip install -r requirements.txt
uvicorn server:app --port 8001 --reload
```

### Talk to the agent live (browser)

```bash
curl -X POST http://localhost:8000/api/agents/<agent-id>/connect/ \
  -H "Host: demo.localhost" \
  -H "Authorization: Api-Key <key>"
# Returns: {"room_url": "...", "caller_token": "..."}
# Open room_url in a browser — you're now in the WebRTC room with the agent bot
```

### Run a scenario in audio-fidelity mode

```bash
shunya tests run <agent-id> --scenario booking_happy_path --mode audio --wait
```

**What happens under the hood:**
1. Django creates a `TestRun` and dispatches `run_scenario_task` via Celery (in the `celery_worker` container)
2. `AudioCaller._connect()` → `POST /connect` on the **pipecat** server (:8001) → Daily room created (`max_participants: 10`), agent pipeline starts, agent bot joins. A readiness event is registered. The response includes an `observer_url` (pre-authed browser join link), which the runner saves to `TestRun.observer_url` *before* the call starts so a human can listen in live.
3. `AudioCaller.run_scenario(..., recording_id=run.id)` → `POST /caller/run` on the pipecat server
4. `/caller/run` **waits for the agent's TTS WebSocket to connect** (readiness gate), then proxies to the **caller** service (:8002) `POST /run` — a separate process with its own Daily context
5. `ScenarioCallerBot` joins the same room; for each step:
   - Synthesizes step text → ElevenLabs TTS **(PCM via `output_format=pcm_16000` query param)**
   - Writes the PCM to a Daily **virtual microphone** (from the event-loop thread — devices are thread-affine)
   - Agent bot hears it → Silero VAD → ElevenLabs Scribe v2 STT → Claude Haiku → ElevenLabs TTS → Daily output
   - Caller bot captures agent audio from a Daily **virtual speaker** → ElevenLabs Scribe v2 (REST) → transcript turn
   - Both sides are appended to a mono WAV
6. Caller writes `/recordings/<run-id>.wav`, returns `{transcript, recording_file}`
7. Full transcript returned to Django → LLM judge scores it

### Pipecat agent server endpoints (:8001)

| Endpoint | Purpose |
|---|---|
| `POST /connect` | Start agent pipeline in a new Daily room, return room URL + caller token + `observer_url` |
| `POST /caller/run` | Wait for agent readiness, then dispatch the caller bot (proxies to :8002) |
| `GET /health` | Liveness check |

### Caller bot service endpoints (:8002)

| Endpoint | Purpose |
|---|---|
| `POST /run` | Run `ScenarioCallerBot` through a full scenario; write WAV; return transcript |
| `GET /health` | Liveness check |

### Listening to a call — live or recorded

**Live (while the call is in progress):** run an audio test with `--wait` and the CLI prints a
join link as soon as the run goes `running`. Open it in a browser to drop into the Daily room and
hear both bots in real time (up to 8 observers per call).

```bash
shunya tests run <agent-id> --scenario booking_happy_path --mode audio --wait
# →  👁  Join to observe: https://<domain>.daily.co/<room>?t=<token>
```

The link is also stored on the run (`observer_url`) and shown by `shunya tests show <run-id>`
while the run is still `running`. Each call is its own ephemeral room, so there's no single
"all calls" URL — the link is per run.

**Recorded (after the call):**

```bash
shunya tests transcript <run-id>     # prints the 🔊 recording link for audio runs
shunya tests audio <run-id>          # prints + opens the link in your browser
shunya tests audio <run-id> --no-open
# Or open directly:  http://localhost:8000/recordings/<run-id>.wav
# Or on the host filesystem:  ./recordings/<run-id>.wav
```

---

## 13. Adding a New Scenario

Create a YAML file in `/scenarios`:

```yaml
name: my_scenario
description: What this tests.
persona: >
  You are a [caller type]. [Behaviour description].
steps:
  - "Opening message"
  - "[stutter] Hard to understand message"
  - "[interrupt] Interruption mid-sentence"
  - "My phone is [phone:\"415-555-0100\"]"
  - "[slow_speech] Deliberate... slow... speech"
  - "[background_noise] Message with noise"
  - "[hard_input:\"difficult value\"] Message with hard input"
assertions:
  - agent_acknowledges_frustration
  - no_hallucinated_policy
rubric:
  instruction_following: 1.0
  goal_completion: 1.5
  interruption_handling: 2.0
  csat_tone: 1.0
  safety: 1.0
```

Load it:

```bash
python manage.py tenant_command load_scenarios --schema=demo \
  --dir /path/to/Shunya/scenarios --force
```

### Voice Quirks DSL Reference

| Tag | Effect in text mode | Effect in audio mode |
|---|---|---|
| `[stutter]` | Sent as-is to agent | Future: ElevenLabs stutter synthesis |
| `[pause:3s]` | Stripped | Future: 3s silence injected |
| `[interrupt]` | Logged as quirk | Future: interrupts agent mid-sentence |
| `[background_noise]` | Stripped | Future: noise bed mixed in |
| `[slow_speech]` | Stripped | Future: slower TTS rate |
| `[hard_input:"value"]` | Value stripped, logged | Spoken verbatim by TTS |
| `[email:"addr"]` | Stripped, logged | Spoken verbatim |
| `[phone:"num"]` | Stripped, logged | Spoken verbatim |

---

## 14. Monitoring & Alerts

```bash
# Create an alert: fire webhook if avg latency > 500ms
curl -X POST http://localhost:8000/api/alerts/ \
  -H "Host: demo.localhost" \
  -H "Authorization: Api-Key <key>" \
  -d '{
    "agent": "<agent-id>",
    "metric_name": "avg_latency_ms",
    "operator": "gt",
    "threshold": 500,
    "webhook_url": "https://hooks.slack.com/your-webhook",
    "is_active": true
  }'

# View alert events
curl http://localhost:8000/api/alert-events/ \
  -H "Host: demo.localhost" \
  -H "Authorization: Api-Key <key>"
```

Supported operators: `gt`, `lt`, `gte`, `lte`, `eq`

Available metric names: `avg_latency_ms`, `p95_latency_ms`, `duration_s`, `turn_count`, `interruption_count`

---

## 15. Common Issues

| Error | Cause | Fix |
|---|---|---|
| `role "postgres" does not exist` | Local Postgres has no `postgres` user | Set `DB_USER` to your macOS username |
| `relation "testing_scenario" does not exist` | Tenant schema not migrated | Create tenant via shell (step 4) |
| `403 Forbidden` on API | Missing or wrong API key | Generate key (step 4), pass as `Authorization: Api-Key <key>` |
| Test run stuck in `queued` | Celery worker not running | Start `celery -A config worker` |
| Test run queues but never completes | Celery task runs in `public` schema (no tables) | Ensure tasks pass `schema_name=connection.schema_name` — already fixed in code |
| Judge scores all `0.0` | `score` column was `integer` type | `ALTER COLUMN score TYPE double precision USING score::double precision` in Postgres |
| `Host: demo.localhost` not routing | django-tenants needs Host header | Always pass `-H "Host: demo.localhost"` in curl |
| CLI shows `403 Forbidden` | `SHUNYA_TENANT_HOST` not set | `export SHUNYA_TENANT_HOST=demo.localhost` |
| Judge scores show "pending" after `--wait` | Judge Celery task still running | Run `shunya tests show <run-id>` ~15s later for final scores |
| Code change in `runner.py`/`judge.py`/tasks has no effect | `celery_worker` container doesn't auto-reload | `docker-compose restart celery_worker` |
| `pipecat` container crashes / native panic | `daily-python` on Python 3.14 or ARM64 | Containers are pinned to `python:3.12` + `--platform=linux/amd64`; rebuild with `docker-compose build pipecat caller` |
| Audio run: agent never responds, caller "Timed out waiting for agent to start speaking" | Agent isn't hearing the caller (silence/no VAD) | Usually the **MP3-not-PCM** bug: ElevenLabs `output_format` must be a **query param**, not a JSON body field (in the body it returns MP3, which is noise to VAD). Already fixed in `caller_bot._synthesize_tts`. |
| Audio run: agent TTS fails with empty-body **HTTP 403** | `voice_id` empty → malformed ElevenLabs URL (`//multi-stream-input`) | Guarded with `voice_id or DEFAULT` in `pipeline.py` and Django `caller.py`; ensure the agent has a valid ElevenLabs voice ID |
| `account-missing-payment-method` from Daily | Daily SDK joins need a billing method on the Daily account | Add a payment method in the Daily dashboard (room creation is free; SDK participants are not) |
| ElevenLabs TTS WebSocket 403 / `paid_plan_required` | WS streaming TTS and library voices need a paid ElevenLabs plan | Use the account's own premade voices; a paid plan is required for WS streaming TTS |
| Audio injected but agent hears silence | `write_frames` called from a worker thread | Daily devices are thread-affine — write from the event-loop thread (no `asyncio.to_thread`). Already fixed. |
| `/recordings/<id>.wav` 404 | No recording for that run (text mode, or run predates the feature) | Recordings only exist for audio-mode runs; check `./recordings/` on the host |
