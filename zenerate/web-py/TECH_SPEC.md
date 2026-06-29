# TECH_SPEC — Shunya

> **Status: as-built.** This spec reflects what shipped. The original decision tables (T1–T7) are kept for history; the LOCKED section and everything below match the running system. Key build-time changes vs the original PLAN: STT = ElevenLabs Scribe v2 (not Deepgram), agent LLM = Claude Haiku 4.5 (not GPT-4o), the synthetic caller is a **separate service**, and the whole stack is **Docker-first** (Daily SDK needs Python 3.12). See PLAN.md "Amendments During Build".

---

## System Components (as-built)

```
┌──────────────────┐     ┌─────────────────────────┐
│   CLI (Typer)    │     │  Browser (Daily.co SDK)  │
└────────┬─────────┘     └────────────┬────────────┘
         │ HTTP + Api-Key             │ WebRTC
         ▼                            ▼
┌─────────────────────────┐   ┌──────────────────────────┐
│   Django API (:8000)    │   │   Pipecat agent (:8001)   │
│ (DRF + django-tenants)  │◄─▶│        (FastAPI)          │
│                         │   │ Daily → Scribe v2 STT     │
│ /api/agents/{id}/chat/  │   │  → Claude Haiku → 11Labs  │
│ /api/agents/{id}/connect│   └─────────────┬─────────────┘
│ /api/test-runs/         │     /caller/run │ (HTTP)
│ /api/metrics,/alerts/   │                 ▼
│ /recordings/<run>.wav   │   ┌──────────────────────────┐
└──────────┬──────────────┘   │   Caller bot (:8002)      │
           │                  │      (FastAPI)            │
           │                  │ ScenarioCallerBot joins   │
           │                  │ Daily room: TTS in (mic), │
           │                  │ Scribe v2 on agent audio  │
           │                  │ → writes /recordings/*.wav│
  ┌────────┴────────┐         └──────────────┬────────────┘
  │   PostgreSQL    │   ┌──────────────┐      │ WebRTC
  │ (schema/tenant) │   │    Redis     │      ▼ (Daily room)
  └─────────────────┘   │(Celery broker)│  [agent bot ↔ caller bot]
                        └──────┬───────┘
                               │
                     ┌─────────▼──────────┐
                     │   Celery Workers   │
                     │  TextCaller runner │
                     │  AudioCaller runner│
                     │  LLM judge         │
                     │  metrics + alerts  │
                     └────────────────────┘

External APIs: Claude Haiku 4.5 (agent brain), Claude Sonnet 4.6 (LLM judge),
               ElevenLabs (TTS + Scribe v2 STT), Daily.co (WebRTC transport)

Deployment: docker-compose — postgres, redis, django, celery_worker,
            celery_beat, pipecat (:8001, py3.12/amd64), caller (:8002, py3.12/amd64).
            ./recordings is bind-mounted into caller (writes) and django (serves).
```

---

---

# DECISION TABLES

---

## T1 — Pipecat Server Deployment Model
*How is the Pipecat voice pipeline deployed relative to Django?*

| # | Option | Pros | Cons | Best For |
|---|---|---|---|---|
| A | **Separate FastAPI service** (standalone Python process, Django calls it via HTTP) | Clean separation; Pipecat and Django scale independently; crash in one doesn't affect the other | Two services to run locally; slightly more wiring | Production-grade, showcases service design |
| B | **Same process as Django** (Pipecat runs as a Django view or async handler) | Single process, simpler local dev | Django's WSGI/ASGI isn't designed for long-lived WebRTC sessions; fragile | Prototypes only |
| C | **Per-call subprocess** (Django spawns a Pipecat process per call, tears it down after) | Total isolation per call; crash doesn't affect other calls | High overhead; complex process management | High-scale production (overkill for assessment) |

**Decision:** ___

---

## T2 — Pipecat ↔ Django Communication
*How do the Pipecat server and Django API share data during a call?*

| # | Option | Pros | Cons | Best For |
|---|---|---|---|---|
| A | **REST API calls** (Pipecat GETs agent config from Django; POSTs call events back) | Decoupled, standard, easy to test | Network hop on every event; slight latency overhead | Clean architecture, good for demo |
| B | **Shared Postgres** (Pipecat writes directly to DB using same models) | Fast, no extra HTTP; single source of truth | Couples Pipecat to Django's DB schema; breaks separation | Monolith-first, fast to build |
| C | **Redis pub/sub** (Pipecat publishes events; Django Channels consumer writes to DB) | Fully async, real-time; decoupled | More moving parts; harder to debug | High-throughput production |

**Decision:** ___

---

## T3 — Transcript Storage Format
*How are call transcripts stored in Postgres?*

| # | Option | Pros | Cons | Best For |
|---|---|---|---|---|
| A | **JSONB blob on Call** (`transcript` = `[{speaker, text, ts_ms, quirks}]`) | Simple, one row per call, fast reads | Hard to query individual turns; no per-turn indexing | Assessment — transcripts read as a whole unit |
| B | **Normalized `Turn` table** (one row per turn, FK to Call) | Queryable per turn, filterable by speaker/timestamp | More rows, slightly heavier writes during call | Analytics-heavy use cases |
| C | **JSONB on separate `Transcript` model** (1:1 with Call, JSONB turns) | Keeps Call table lean; full transcript in one fetch | Still no per-turn indexing | Balance — clean model without over-normalizing |

**Decision:** ___

---

## T4 — Celery Task Granularity for Test Runner
*How is a test run broken into Celery tasks?*

| # | Option | Pros | Cons | Best For |
|---|---|---|---|---|
| A | **One task per test run** (single Celery task runs all steps of one scenario sequentially) | Simple, easy to track status, minimal overhead | Can't parallelize steps within a scenario | Most use cases — scenarios are short (5-10 turns) |
| B | **One task per scenario step** (each turn dispatched as its own task, chained) | Maximum parallelism within a scenario | Complex task chaining; harder to maintain conversation state across tasks | Long multi-step scenarios at scale |
| C | **One task per test run, grouped runs parallelised** (`group()` of tasks, one per scenario in a batch) | Parallel across scenarios, sequential within; best balance | Slightly more Celery config | Production-grade, right abstraction |

**Decision:** ___

---

## T5 — YAML Scenario Storage & Loading
*Where do scenarios live and how are they loaded?*

| # | Option | Pros | Cons | Best For |
|---|---|---|---|---|
| A | **Files on disk, loaded into DB at startup** (YAML files in `scenarios/` dir; management command imports them) | Git-versioned, diffable, familiar dev workflow | Requires a sync step; files and DB can drift | Engineering-first teams, assessment |
| B | **DB only** (scenarios created via API/CLI, stored as text in DB) | Single source of truth; CLI-driven workflow | Can't diff scenarios in git unless you export them | API-first platforms |
| C | **DB primary, YAML import/export commands** (`shunya scenarios import <file>`, `shunya scenarios export <id>`) | Best ergonomics — git workflow + API control | More CLI commands to build | Production SaaS |

**Decision:** ___

---

## T6 — Daily.co Room Lifecycle
*How are Daily.co rooms created and managed per agent?*

| # | Option | Pros | Cons | Best For |
|---|---|---|---|---|
| A | **Persistent room per agent** (one room created when agent is registered, reused for all calls) | Simple — one API call at agent creation; no per-call provisioning | Room URL never changes; less isolation between calls | Assessment, low call volume |
| B | **Ephemeral room per call** (new Daily room created at call start, deleted after) | Clean isolation; proper call lifecycle; matches how ElevenLabs does it | Daily API call on every inbound connection; small latency | Production pattern — right approach |
| C | **Room pool** (pre-provisioned pool of rooms, assigned on demand) | Near-zero connection latency | Complex pool management | High-throughput, not needed here |

**Decision:** ___

---

## T7 — CLI Auth Pattern
*How does the CLI authenticate with the Django API?*

| # | Option | Pros | Cons | Best For |
|---|---|---|---|---|
| A | **Static API key** (`SHUNYA_API_KEY` env var, Bearer token on every request) | Simple, stateless, easy to test, scriptable | No expiry, no rotation built-in | Assessment, developer tools |
| B | **JWT** (`shunya login` → stores token in `~/.shunya/config`, auto-refreshes) | Proper expiry, more secure, polished UX | More auth logic to build (login command, token store, refresh) | Production CLI (Vercel, Railway style) |
| C | **Per-tenant API key from Django admin** (key scoped to tenant, set once in env) | Tenant-aware from the start; aligns with multi-tenancy model | Slightly more setup in Django (API key model) | Multi-tenant SaaS — correct approach |

**Decision:** ___

---

---

# LOCKED TECHNICAL DECISIONS

| Decision | Choice | Notes |
|---|---|---|
| T1 — Pipecat deployment | **FastAPI** (separate service) → **now two services** | Django = control plane. Voice runtime split into **pipecat (:8001, agent pipeline)** and **caller (:8002, synthetic caller bot)** because `daily-python` allows only one `CallClient` per process. Both are py3.12/amd64 containers. |
| T2 — Pipecat ↔ Django IPC | **A — REST API** | Pipecat GETs agent config on call start; POSTs call events to Django internal endpoints. |
| T3 — Transcript storage | **C — Separate `Transcript` model** | 1:1 with Call. Turns stored as JSONB array `[{speaker, text, ts_ms, quirks}]`. Keeps Call table lean; full transcript in one fetch. |
| T4 — Celery task granularity | **C — One task per run, runs grouped** | Sequential steps within a scenario; parallel across scenarios via Celery `group()`. Idiomatic Celery. |
| T5 — Scenario storage | **A — YAML files → DB** | YAML files in `scenarios/` dir; `manage.py load_scenarios` imports them. Git-versioned, diffable. |
| T6 — Daily.co room lifecycle | **B — Ephemeral room per call** | New room on call start (human or AudioCaller bot), deleted after. Matches ElevenLabs pattern. |
| T7 — CLI auth | **C — Per-tenant API key** | Key scoped to tenant, stored in DB (hashed). Set via `SHUNYA_API_KEY` env var. |

---

---

# DATA MODELS

All models below live in the **per-tenant Postgres schema** (django-tenants) unless marked `[public]`.

---

## Tenants [public schema]

```python
# django-tenants built-ins
Tenant:         schema_name, name, created_on
Domain:         domain, tenant (FK), is_primary

TenantAPIKey:   id (UUID), key_hash (str), key_prefix (str, first 8 chars for display),
                tenant (FK → Tenant), created_at, last_used_at
```

---

## Agents app

```python
Agent:
  id            UUID, primary key
  name          str
  system_prompt text
  voice_id      str              # ElevenLabs voice ID
  status        enum [active, inactive]
  created_at    datetime
  updated_at    datetime

Call:
  id              UUID, primary key
  agent           FK → Agent
  source          enum [human, test_text, test_audio]
  daily_room_url  str (nullable)   # set for human + audio fidelity calls
  daily_room_name str (nullable)
  status          enum [in_progress, completed, failed]
  started_at      datetime
  ended_at        datetime (nullable)
  created_at      datetime

Transcript:                      # 1:1 with Call
  id        UUID, primary key
  call      OneToOneField → Call
  turns     JSONB                # [{speaker: "agent"|"caller", text, ts_ms, quirks: [str]}]
  created_at datetime

CallMetric:                      # 1:1 with Call, written post-call
  id                       UUID, primary key
  call                     OneToOneField → Call
  total_duration_ms        int
  turn_count               int
  first_response_latency_ms  int
  avg_turn_latency_ms      float
  interruption_count       int
  sentiment                enum [positive, neutral, negative]
  created_at               datetime
```

---

## Testing app

```python
Scenario:
  id            UUID, primary key
  name          str (unique per tenant)
  description   str
  yaml_content  text             # raw source YAML
  persona       text
  steps         JSONB            # [{text, quirks: [str]}] — parsed from YAML
  assertions    JSONB            # [str]
  rubric        JSONB            # {field: weight} — overrides default rubric
  created_at    datetime
  updated_at    datetime

TestRun:
  id              UUID, primary key
  agent           FK → Agent
  scenario        FK → Scenario
  mode            enum [text, audio]   # text = TextCaller; audio = AudioCaller bot-to-bot
  status          enum [queued, running, completed, failed]
  celery_task_id  str (nullable)
  call            FK → Call (nullable) # set for audio mode — the bot-to-bot call record
  observer_url    URLField (blank)     # audio mode — pre-authed Daily join link for live listen-in
  started_at      datetime (nullable)
  completed_at    datetime (nullable)
  created_at      datetime

TestResult:                      # 1:1 with TestRun
  id                  UUID, primary key
  test_run            OneToOneField → TestRun
  passed              bool
  transcript          JSONB      # same turn format as Transcript.turns
  assertion_results   JSONB      # [{assertion, passed: bool}]
  created_at          datetime

JudgeScore:                      # one row per rubric field per TestResult
  id          UUID, primary key
  test_result FK → TestResult
  field       str                # instruction_following | goal_completion |
                                 # interruption_handling | tool_call_accuracy |
                                 # csat_tone | safety
  score       float (0.0–1.0)    # NOTE: column is double precision, not integer
  reasoning   text               # one-line Claude (Sonnet 4.6) explanation
  passed      bool               # score >= 0.7
  created_at  datetime
```

---

## Monitoring app

```python
AlertConfig:
  id           UUID, primary key
  agent        FK → Agent
  metric_name  str               # avg_turn_latency_ms | interruption_count | sentiment | ...
  operator     enum [gt, lt, gte, lte, eq]
  threshold    float
  webhook_url  str
  is_active    bool
  created_at   datetime

AlertEvent:
  id              UUID, primary key
  alert_config    FK → AlertConfig
  call            FK → Call
  triggered_at    datetime
  metric_value    float
  payload_sent    JSONB          # full webhook body for debugging
```

---

---

# API ENDPOINT MAP

## Django DRF (tenant-scoped, all require `Authorization: Api-Key <key>`)

```
# Agents
GET    /api/agents/
POST   /api/agents/
GET    /api/agents/{id}/
PATCH  /api/agents/{id}/
DELETE /api/agents/{id}/

# Calls
GET    /api/agents/{id}/calls/
GET    /api/calls/{id}/
GET    /api/calls/{id}/transcript/
GET    /api/calls/{id}/metrics/

# Scenarios
GET    /api/scenarios/
POST   /api/scenarios/
GET    /api/scenarios/{id}/
PATCH  /api/scenarios/{id}/
DELETE /api/scenarios/{id}/

# Test Runs
POST   /api/agents/{id}/test-runs/     # triggers run; returns TestRun id immediately
GET    /api/agents/{id}/test-runs/
GET    /api/test-runs/{id}/
GET    /api/test-runs/{id}/results/    # includes JudgeScores + assertion_results

# Metrics
GET    /api/agents/{id}/metrics/       # ?from=ISO&to=ISO  →  aggregate stats
GET    /api/calls/{id}/metrics/

# Alerts
GET    /api/agents/{id}/alerts/
POST   /api/agents/{id}/alerts/
GET    /api/alerts/{id}/
PATCH  /api/alerts/{id}/
DELETE /api/alerts/{id}/
GET    /api/alerts/{id}/events/
```

## Agent chat endpoint (used by TextCaller)

```
POST   /api/agents/{id}/chat/          # body: {message, conversation_id}
                                       # returns: {response, conversation_id, ts_ms}
```

## Internal endpoints (Pipecat → Django)

```
POST   /internal/calls/start/          # body: {agent_id, source, daily_room_url, daily_room_name}
POST   /internal/calls/{id}/turn/      # body: {speaker, text, ts_ms, quirks}
POST   /internal/calls/{id}/end/       # triggers post-call Celery task (metrics + judge)
```

## Recordings (served by Django, audio mode)

```
GET    /recordings/<run-id>.wav        # mono 16kHz WAV of the bot-to-bot call; inline audio/wav
```

## FastAPI — Pipecat agent server (:8001)

```
GET    /health
POST   /connect                        # body: {agent_id, system_prompt, voice_id}
                                       #   creates Daily room (max_participants: 10), starts the agent
                                       #   pipeline (bot joins), returns
                                       #   {room_url, room_name, caller_token, observer_url}
                                       #   observer_url = pre-authed browser join link for live listen-in
POST   /caller/run                     # body: {room_url, room_token, steps, voice_id, recording_id}
                                       #   waits for agent TTS readiness, then forwards to the caller service
```

## FastAPI — Caller bot service (:8002)

```
GET    /health
POST   /run                            # body: {room_url, room_token, steps, voice_id, recording_id}
                                       #   ScenarioCallerBot joins the room, runs the scenario,
                                       #   writes /recordings/<recording_id>.wav,
                                       #   returns {transcript, recording_file}
```

> The agent pipeline and the caller bot are **separate processes/containers** — `daily-python` cannot host two `CallClient`s (or call `Daily.init()` twice) in one process.

---

---

# DIRECTORY STRUCTURE

```
shunya/
├── django_api/
│   ├── manage.py
│   ├── config/
│   │   ├── settings/
│   │   │   ├── base.py
│   │   │   ├── local.py
│   │   │   └── production.py
│   │   ├── urls.py
│   │   └── celery.py
│   ├── apps/
│   │   ├── tenants/            # Tenant, Domain, TenantAPIKey + auth middleware
│   │   ├── agents/             # Agent, Call, Transcript, CallMetric
│   │   │   └── chat.py         # Claude Haiku stateful chat handler (used by TextCaller)
│   │   ├── testing/            # Scenario, TestRun, TestResult, JudgeScore
│   │   │   ├── caller.py       # CallerInterface + TextCaller + AudioCaller
│   │   │   ├── judge.py        # Claude LLM judge
│   │   │   ├── runner.py       # Celery task: mode-aware, delegates to caller
│   │   │   └── management/
│   │   │       └── commands/
│   │   │           └── load_scenarios.py
│   │   └── monitoring/         # AlertConfig, AlertEvent + Celery beat tasks
│   └── requirements.txt
│
├── pipecat_agent/              # py3.12 / linux/amd64 (Daily SDK requirement)
│   ├── server.py               # FastAPI: /connect (agent) + /caller/run (proxy to caller svc)
│   ├── pipeline.py             # Agent pipeline: Daily→Scribe v2→Claude Haiku→ElevenLabs
│   │                           #   incl. VADProcessor(Silero) before STT + RetryingElevenLabsTTSService
│   ├── caller_server.py        # FastAPI (:8002): /run → ScenarioCallerBot
│   ├── caller_bot.py           # ScenarioCallerBot: virtual mic/speaker, TTS, Scribe, WAV recording
│   ├── Dockerfile              # FROM --platform=linux/amd64 python:3.12-slim
│   └── requirements.txt        # pipecat-ai[daily,elevenlabs,silero,anthropic]
│
├── cli/
│   ├── main.py                 # Typer app root + main() wrapper (clean ShunyaError handling)
│   └── client.py               # Thin HTTP client; raises ShunyaError on 4xx/connection errors
│
├── scenarios/                  # YAML scenario files (T5)
│   ├── angry_customer_refund.yaml
│   ├── booking_happy_path.yaml
│   └── edge_case_gibberish.yaml
│
├── recordings/                 # bind-mounted: caller writes WAVs, django serves them
├── setup.py                    # `pip install -e .` → `shunya` command (entry: cli.main:main)
├── docker-compose.yml          # postgres, redis, django, celery_worker, celery_beat, pipecat, caller
└── RUNBOOK.md
```

> Note: the CLI is a flat module (`cli/main.py` + `cli/client.py`), not a `shunya/commands/` package. Metrics/alerts live in the Django `monitoring` app and REST API, not as separate CLI command modules.

---

---

# CALLER INTERFACE

Both callers are built. The test runner selects based on `TestRun.mode`.

```python
# django_api/apps/testing/caller.py

class CallerInterface:
    def send(self, turn_text: str, conversation_id: str) -> dict: ...

class TextCaller(CallerInterface):
    """Strips Voice Quirks DSL, calls AgentChat (Claude Haiku) in-process."""
    def send(self, turn_text: str, conversation_id: str) -> dict:
        # strips [stutter], [pause:3s] etc., runs Claude Haiku, returns the reply
        ...

class AudioCaller(CallerInterface):
    """Full-scenario (not turn-by-turn). Provisions a Daily room via the Pipecat
    server's /connect, then POSTs the whole scenario to /caller/run, which runs
    ScenarioCallerBot (ElevenLabs TTS in, Scribe v2 on the agent's audio out)."""
    def run_scenario(self, steps, conversation_id, recording_id="") -> list[dict]:
        ...
    def send(self, *a, **k):
        raise NotImplementedError("AudioCaller is full-scenario, not turn-by-turn.")

def get_caller(mode, agent) -> CallerInterface:
    return TextCaller(agent) if mode == "text" else AudioCaller(agent)
```

> The runner branches on mode: audio mode calls `caller.run_scenario(...)` (whole scenario handed to the bot); text mode loops `caller.send(...)` per step.

---

---

# BUILD ORDER

| Phase | What | Key files |
|---|---|---|
| 1 | Django foundation: models + migrations + tenant setup + API key auth | `apps/tenants/`, all `models.py` files |
| 2 | Agent chat endpoint + DRF viewsets for all resources | `apps/agents/chat.py`, `apps/*/views.py`, `config/urls.py` |
| 3 | Pipecat voice agent: pipeline + Daily room lifecycle | `pipecat_agent/server.py`, `pipecat_agent/pipeline.py` |
| 4 | Text mode: YAML loader + TextCaller + Celery runner | `apps/testing/caller.py`, `apps/testing/runner.py`, `scenarios/` |
| 5 | LLM Judge: Claude rubric scoring + JudgeScore writes | `apps/testing/judge.py` |
| 6 | Audio fidelity mode: ScenarioCallerBot (separate caller service) | `pipecat_agent/caller_server.py`, `pipecat_agent/caller_bot.py`, `apps/testing/caller.py` |
| 7 | Monitoring: post-call metrics + AlertConfig + webhook | `apps/monitoring/` |
| 8 | CLI: Typer control plane | `cli/` |
| 9 | Tests: pytest + bot-to-bot integration test | `tests/` |
| 10 | Call recording + browser playback | `caller_bot.py`, `config/recordings.py` |

---

---

# AUDIO MODE — ENGINEERING NOTES

Bringing audio fidelity mode up end-to-end was the hardest part of the build. Recording these here so the next person doesn't re-derive them.

### Version / platform pins (non-negotiable)
- **`daily-python` has no Python 3.14 wheels** and panics natively → the Pipecat containers are pinned to **`python:3.12`**.
- `daily-python`'s native lib misbehaves on **ARM64** → both voice images build with **`--platform=linux/amd64`** (runs under emulation on Apple Silicon).
- **Pipecat 1.4** moved/renamed a lot vs older examples:
  - STT needs an `aiohttp_session`: `ElevenLabsSTTService(api_key=..., aiohttp_session=...)`
  - LLM: `AnthropicLLMService(settings=AnthropicLLMService.Settings(model=..., system_instruction=...))` (not `system=`)
  - TTS: `ElevenLabsTTSService(settings=ElevenLabsTTSService.Settings(voice=...))`
  - **VAD is NOT a `DailyParams` field anymore.** Use a standalone `VADProcessor(vad_analyzer=SileroVADAnalyzer(...))` placed **before** the segmented STT so it emits `VADUserStartedSpeaking/Stopped` frames the STT consumes.

### Two-process rule
`daily-python` allows only one `CallClient` / one `Daily.init()` per process. The agent pipeline owns one, so the **caller bot runs in its own service** (`caller_server.py`, :8002). The Pipecat server proxies `/caller/run` → caller `/run`.

### Sending audio into a Daily room
- Use a `VirtualMicrophoneDevice` selected via `client_settings.inputs.microphone.settings.deviceId` (deviceId must be nested under `settings`).
- **Daily devices are thread-affine** — call `write_frames` from the event-loop thread, **not** via `asyncio.to_thread` (which silently injects nothing).
- Capture the agent's audio with a `VirtualSpeakerDevice` + `Daily.select_speaker_device(...)`, polled in a background task.

### The MP3-not-PCM trap (root cause of "agent hears nothing")
ElevenLabs ignores `output_format` when it's in the **JSON body** and returns **MP3** (`ID3…`). Written as raw PCM it's high-RMS noise → Silero VAD scores it ~0.06 (not speech) → the agent never hears the caller. **Fix: `output_format=pcm_16000` must be a query parameter.** With that, VAD confidence jumps to ~0.99.

### Other gotchas
- **Empty `voice_id`** (agent record had none) → URL `…/text-to-speech//multi-stream-input` → ElevenLabs GCP edge returns an opaque empty-body **HTTP 403**. Guard with `voice_id or DEFAULT`.
- ElevenLabs **WebSocket TTS streaming requires a paid plan**; **library voices require a paid plan via API** — use the account's own premade voices.
- **Daily SDK joins require a payment method on the Daily account** (`account-missing-payment-method`), even for free room creation.
- A **readiness gate** (`AGENT_READY` event set on the TTS `on_connected` handler) makes `/caller/run` wait until the agent's TTS WebSocket is up, so the first caller turn isn't spoken into a deaf room.
- `RetryingElevenLabsTTSService` retries the TTS WS connect with backoff (transient edge 403s).

### Live listen-in (observer URL)
`/connect` mints a third, non-owner **observer token** and returns `observer_url = "{room_url}?t={token}"`; rooms are created with `max_participants: 10` to leave headroom for human observers. The runner calls `AudioCaller._connect()` *before* the scenario starts and persists the link to `TestRun.observer_url` (`URLField`, migrations 0002/0004). The CLI prints **👁 Join to observe** during a `--wait` poll the moment the run reports `running`. This is per-run live monitoring; an aggregate "all calls" dashboard URL isn't possible because each call is its own ephemeral room.

