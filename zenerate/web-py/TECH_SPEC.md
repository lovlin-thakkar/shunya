# TECH_SPEC — Shunya

> **Status: as-built.** This spec reflects what shipped. The original decision tables (T1–T7) are kept for history; the LOCKED section and everything below match the running system. Key build-time changes vs the original PLAN: STT = ElevenLabs Scribe v2 (not Deepgram), agent LLM = Claude Haiku 4.5 (not GPT-4o), the synthetic caller is a **separate service**, the whole stack is **Docker-first** (Daily SDK needs Python 3.12), and multi-tenancy uses **RLS single-schema** (not django-tenants).

---

## System Components (as-built)

```
┌──────────────────┐     ┌─────────────────────────┐     ┌──────────────────┐
│   CLI (Typer)    │     │  Browser (Daily.co SDK)  │     │  Next.js UI      │
└────────┬─────────┘     └────────────┬────────────┘     └────────┬─────────┘
         │ HTTP + Api-Key             │ WebRTC                   │ Knox auth
         ▼                            ▼                          ▼
┌─────────────────────────┐   ┌──────────────────────────┐
│   Django API (:8000)    │   │   Pipecat agent (:8001)   │
│ (DRF + RLS multi-tenant)│◄─▶│        (FastAPI)          │
│                         │   │ Daily → Scribe v2 STT     │
│ /api/v1/agents/         │   │  → Claude Haiku → 11Labs  │
│ /api/v1/test-runs/      │   └─────────────┬─────────────┘
│ /api/v1/agents/{id}/sync-elevenlabs/│    │
│ /recordings/<run>.wav   │     /caller/run │ (HTTP)
└──────────┬──────────────┘                 ▼
           │                  ┌──────────────────────────┐
           │                  │   Caller bot (:8002)      │
           │                  │      (FastAPI)            │
           │                  │ ScenarioCallerBot:        │
           │                  │  TTS in (mic), Scribe v2  │
           │                  │  on agent audio, WAV out  │
           │                  │ EvalAgent (remote EL):    │
           │                  │  ConvAI WS + Scorer class │
   ┌───────┴────────┐        └──────────────┬────────────┘
   │   PostgreSQL    │   ┌──────────────┐      │ WebRTC / WS
   │ (single-schema  │   │    Redis     │      ├── Daily room (audio)
   │  RLS isolation) │   │(Celery broker)│     └── ElevenLabs ConvAI WS
   └─────────────────┘   └──────┬───────┘
                                │
                      ┌─────────▼──────────┐
                      │   Celery Workers   │
                      │  TextCaller runner │
                      │  AudioCaller runner│
                      │  RemoteAudioCaller │
                      │  LLM judge         │
                      │  metrics + alerts  │
                      └────────────────────┘

External APIs: Claude Haiku 4.5 (agent brain + live scorer), Claude Sonnet 4.6 (LLM judge),
               ElevenLabs (TTS + Scribe v2 STT + ConvAI WS), Daily.co (WebRTC transport)

Deployment: docker-compose — postgres, redis, django, celery_worker,
             pipecat (:8001, py3.12/amd64), caller (:8002, py3.12/amd64),
             web (:3000, Next.js).
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
| T1 — Pipecat deployment | **FastAPI** (separate service) → **now two services** | Django = control plane. Voice runtime split into **pipecat (:8001, agent pipeline)** and **caller (:8002, synthetic caller bot + EvalAgent)** because `daily-python` allows only one `CallClient` per process. Both are py3.12/amd64 containers. |
| T2 — Pipecat ↔ Django IPC | **A — REST API** | Pipecat GETs agent config on call start; POSTs call events to Django internal endpoints. |
| T3 — Transcript storage | **C — Separate `Transcript` model** | 1:1 with Call. Turns stored as JSONB array `[{speaker, text, ts_ms, quirks}]`. Keeps Call table lean; full transcript in one fetch. |
| T4 — Celery task granularity | **C — One task per run, runs grouped** | Sequential steps within a scenario; parallel across scenarios via Celery `group()`. Idiomatic Celery. |
| T5 — Scenario storage | **A — YAML files → DB** | YAML files in `scenarios/` dir; `manage.py load_scenarios` imports them. Git-versioned, diffable. |
| T6 — Daily.co room lifecycle | **B — Ephemeral room per call** | New room on call start (human or AudioCaller bot), deleted after. Matches ElevenLabs pattern. |
| T7 — CLI auth | **C — Per-tenant API key** | Key scoped to tenant, stored in DB (SHA-256 hashed). Set via `SHUNYA_API_KEY` env var. |
| T8 — Multi-tenancy | **RLS single-schema** | Custom `zenlib-mt-py` package, NOT `django-tenants`. All data in one schema, isolated by Postgres RLS on `tenant_id`. |
| T9 — Celery task arg | **`tenant_id` (integer PK)** | Not `schema_name` — workers call `context.current_tenant.set()` to set RLS context. |

---

---

# DATA MODELS

All models below inherit `ActivityTenantBaseModel` (which adds `tenant` FK + RLS) unless marked.
All live in the **single Postgres schema**, isolated by RLS on `tenant_id`.

---

## Tenants

```python
# zenlib-mt-py (packages/mt/)

Tenant:                    id (int PK), name, slug, service_token, created_at
                           # NOT schema_name — RLS single-schema model

TenantAPIKey:              id (UUID PK), key_hash (str, SHA-256), key_prefix (str, first 8 chars),
                           tenant (FK → Tenant), created_at, last_used_at
```

---

## Agents app

```python
Agent:
  id                UUID PK
  name              str
  description       str (blank)
  system_prompt     text
  greeting          text (blank)          # agent's opening line
  voice_id          str (blank)           # ElevenLabs voice ID
  status            enum [active, inactive]
  target_type       enum [builtin, elevenlabs]  # BUILTIN = Pipecat pipeline, ELEVENLABS = remote
  el_agent_id       str (blank)           # ElevenLabs ConvAI agent_id (for remote mode)
  dynamic_variables JSONB (default {})    # injected into ConvAI conversation_initiation_client_data
  created_at        datetime
  updated_at        datetime

ElevenLabsCredential:
  id                UUID PK
  api_key           text                  # write-only; never returned via API
  key_hint          str                   # masked preview (e.g. "sk_0…a1b2")
  tenant            FK (unique)           # one key per tenant

Call:
  id                UUID PK
  agent             FK → Agent
  source            enum [human, test_text, test_audio]
  daily_room_url    URLField (blank)
  daily_room_name   str (blank)
  status            enum [in_progress, completed, failed]
  started_at        datetime (nullable)
  ended_at          datetime (nullable)
  created_at        datetime

Transcript:                      # 1:1 with Call
  id                UUID PK
  call              OneToOneField → Call
  turns             JSONB         # [{speaker: "agent"|"caller", text, ts_ms, quirks: [str]}]
  created_at        datetime

CallMetric:                      # row per metric name per call
  id                UUID PK
  call              FK → Call
  name              str           # total_duration_ms, turn_count, first_response_latency_ms, etc.
  value             float
```

---

## Testing app

```python
Scenario:
  id                UUID PK
  name              str (unique per tenant)
  description       str
  yaml_content      text          # raw source YAML
  persona           text
  steps             JSONB         # [{text, raw, quirks: [{tag, value}]}]
  assertions        JSONB         # [str]
  rubric            JSONB         # {field: weight}
  compatible_agents M2M → Agent   # empty = compatible with any agent
  created_at        datetime
  updated_at        datetime

TestRun:
  id                UUID PK
  agent             FK → Agent
  scenario          FK → Scenario
  mode              enum [text, audio]
  status            enum [queued, running, completed, failed]
  celery_task_id    str (nullable)
  call              OneToOneField → Call (nullable)
  observer_url      URLField (blank)     # pre-authed Daily join link for live listen-in
  error_message     text (blank)         # failure reason if any
  disconnect_reason str (blank)          # why ElevenLabs WS closed mid-conversation
  live_scores       JSONB (default {})   # during-call scores from ScoringSubAgents
  started_at        datetime (nullable)
  completed_at      datetime (nullable)
  created_at        datetime

TestResult:                      # 1:1 with TestRun
  id                UUID PK
  test_run          OneToOneField → TestRun
  passed            bool
  transcript        JSONB        # same turn format as Transcript.turns
  assertion_results JSONB        # [{assertion, passed: bool}]
  created_at        datetime

JudgeScore:                      # one row per rubric field per TestResult
  id                UUID PK
  test_result       FK → TestResult
  field             str          # instruction_following | goal_completion |
                                 # interruption_handling | tool_call_accuracy |
                                 # csat_tone | safety
  score             float (0.0–1.0)
  reasoning         text         # Claude Sonnet explanation
  passed            bool         # score >= 0.7
  created_at        datetime
```

---

## Monitoring app

```python
AlertConfig:
  id                UUID PK
  agent             FK → Agent
  metric_name       str          # avg_latency_ms, p95_latency_ms, duration_s, turn_count, ...
  operator          enum [gt, lt, gte, lte, eq]
  threshold         float
  webhook_url       URLField
  is_active         bool
  created_at        datetime

AlertEvent:
  id                UUID PK
  alert_config      FK → AlertConfig
  call              FK → Call
  triggered_at      datetime (auto_now_add)
  metric_value      float
  payload_sent      JSONB        # full webhook body for debugging
```

---

---

# 3-TIER VERDICT SYSTEM

Shunya evaluates test runs at three levels:

| Tier | When | What | Who | Persisted Where |
|------|------|------|-----|-----------------|
| **1 — Heuristic Assertions** | After scenario steps, before TestResult | Checks known assertion names (e.g. `resolved_within_5_turns`, `agent_acknowledges_frustration`) with simple pattern-matching heuristics. Semantic assertions (`no_hallucinated_policy`) pass heuristically — real eval deferred to judge. | `runner._evaluate_assertions()` synchronous | `TestResult.assertion_results` JSONB |
| **2 — During-Call Live Scores** | After each agent turn (remote mode only) | `Scorer` scores all rubric fields concurrently via `asyncio.gather` (Claude Sonnet), then posts ONE atomic batch to Django per turn. Merge-by-field semantics in `LiveScoresView` prevents concurrent POSTs from race-overwriting. After the last turn, `runner._promote_live_scores()` reads the final batch from DB and writes permanent `JudgeScore` rows. | `EvalAgent` → `Scorer` (plain async class) | `TestRun.live_scores` JSONB → promoted to `JudgeScore` rows |
| **3 — Post-Call LLM Judge** | Not currently wired in production | `judge.evaluate_result()` exists but is not called from production paths — `run_judge_task` was removed from `tasks/__init__.py` and `runner.py` does not call it. Text/audio mode `TestResult` rows have no `JudgeScore` rows; only heuristic assertion results are populated. Remote mode is scored via Tier 2. | `judge.evaluate_result()` (exists, not called) | — |

---

---

# API ENDPOINT MAP

## Django DRF (tenant-scoped)

```
# Auth
GET    /health/                                    # liveness

# Agents
GET    /api/v1/agents/                             # list
POST   /api/v1/agents/                             # create (or sync from ElevenLabs)
GET    /api/v1/agents/{id}/                        # detail
PATCH  /api/v1/agents/{id}/                        # partial update
DELETE /api/v1/agents/{id}/                        # delete
POST   /api/v1/agents/{id}/chat/                   # text-mode conversation (Haiku)
POST   /api/v1/agents/{id}/connect/                # start voice pipeline (browser join link)
POST   /api/v1/agents/{id}/run-evals/              # run all scenarios in parallel (Celery group)
POST   /api/v1/agents/sync-elevenlabs/             # sync agents from ElevenLabs account

# Calls
GET    /api/v1/calls/                              # list
GET    /api/v1/calls/{id}/                         # detail
GET    /api/v1/calls/{id}/transcript/              # transcript
GET    /api/v1/calls/{id}/metrics/                 # call metrics

# Scenarios
GET    /api/v1/scenarios/                          # list
POST   /api/v1/scenarios/                          # create
GET    /api/v1/scenarios/{id}/                     # detail
PATCH  /api/v1/scenarios/{id}/                     # partial update
DELETE /api/v1/scenarios/{id}/                     # delete

# Test Runs
POST   /api/v1/test-runs/                          # create + dispatch
GET    /api/v1/test-runs/{id}/                     # status + live scores + judge scores
GET    /api/v1/test-runs/{id}/results/              # full result with transcript
DELETE /api/v1/test-runs/clear/                     # delete all runs for tenant

# Metrics & Alerts
GET    /api/v1/agents/{id}/metrics/                # aggregate stats (?from=ISO&to=ISO)
GET    /api/v1/agents/{id}/alerts/                 # list alert configs for agent
POST   /api/v1/agents/{id}/alerts/                 # create alert config
GET    /api/v1/alerts/                             # list all alert configs
GET    /api/v1/alerts/{id}/                        # detail
PATCH  /api/v1/alerts/{id}/                        # update
DELETE /api/v1/alerts/{id}/                        # delete
GET    /api/v1/alerts/{id}/events/                 # alert history
GET    /api/v1/alert-events/                       # all alert events

# ElevenLabs Integration
GET    /api/v1/integrations/elevenlabs/            # check if key is configured
PUT    /api/v1/integrations/elevenlabs/            # save ElevenLabs API key
```

## Internal endpoints (Pipecat → Django, service-to-service)

```
POST   /internal/calls/start/          # body: {agent_id, source, daily_room_url, daily_room_name}
POST   /internal/calls/{id}/turn/      # body: {speaker, text, ts_ms, quirks}
POST   /internal/calls/{id}/end/       # triggers post-call Celery task (metrics + judge)
POST   /internal/test-runs/{id}/live-scores/  # body: {turn, scores: [{field, score, passed, reasoning}]}
```

## Recordings

```
GET    /recordings/<run-id>.wav        # mono 16kHz WAV; served by Django _RecordingView
```

## FastAPI — Pipecat agent server (:8001)

```
GET    /health
POST   /connect                        # body: {agent_id, system_prompt, voice_id}
                                       #   creates Daily room (max_participants: 10), starts agent
                                       #   pipeline, returns {room_url, room_name, caller_token, observer_url}
                                       #   Rate-limited: 5 concurrent pipelines
POST   /caller/run                     # body: {room_url, room_token, steps, voice_id, recording_id}
                                       #   waits for agent TTS readiness, proxies to caller /run
```

## FastAPI — Caller bot service (:8002)

```
GET    /health
POST   /run                            # body: {room_url, room_token, steps, voice_id, recording_id}
                                       #   ScenarioCallerBot joins room, runs scenario,
                                       #   writes /recordings/<recording_id>.wav,
                                       #   returns {transcript, recording_file}
POST   /remote/connect                 # provisions Daily room for remote EL agent observer access
                                       #   returns {room_url, room_name, caller_token, observer_url}
POST   /remote/run                     # body: {el_agent_id, steps, agent_api_key, ...}
                                       #   EvalAgent connects to ElevenLabs ConvAI WS,
                                       #   drives scenario steps, bridge audio to Daily room,
                                       #   runs concurrent ScoringSubAgents, returns {transcript, recording_file}
                                       #   Rate-limited: 4 concurrent remote runs
```

> The agent pipeline and the caller bot are **separate processes/containers** — `daily-python` cannot host two `CallClient`s (or call `Daily.init()` twice) in one process.

---

---

# DIRECTORY STRUCTURE (as-built)

```
zenerate/web-py/
├── apps/api/                          # Docker — Django control plane
│   ├── manage.py
│   ├── pyproject.toml
│   ├── Dockerfile
│   ├── src/zenapi/
│   │   └── config/
│   │       ├── settings/__init__.py   # single-file settings, ATONIC_REQUESTS=True, RLS middleware
│   │       ├── urls.py                # root: /health, /api/v1/, /internal/, /recordings/
│   │       └── url_confs/
│   │           ├── urls.py            # health, knox auth, mounts voice + internal
│   │           ├── voice.py           # mounts voice_qa sub-routers under /api/v1/
│   │           └── email.py           # mounts email_pipeline under /api/v1/email/
│   ├── celery.py                      # zenapi.celery app
│   └── tests/                         # pytest suite (RSL-aware conftest)
│       ├── conftest.py
│       ├── factories.py
│       ├── test_multitenant.py
│       ├── test_voice_qa.py
│       ├── test_new_coverage.py
│       ├── test_runner_caller.py
│       ├── test_tasks.py
│       ├── test_live_scoring.py
│       └── email_pipeline/
│
├── packages/
│   ├── mt/                            # zenlib-mt-py (DO NOT MODIFY)
│   │   └── src/zenlib/
│   │       ├── reusable_apps/multitenant/  # Tenant, ActivityTenantBaseModel, middlewares
│   │       └── django_utils/db/pg_rls/    # RLS policy builders
│   │
│   └── agent/                         # zenlib-agent-py (voice_qa + email_pipeline)
│       └── src/zenlib_agentos/zenlib/reusable_apps/
│           ├── voice_qa/              # ★ core product
│           │   ├── models/__init__.py
│           │   ├── views/__init__.py
│           │   ├── urls/agents.py, urls/scenarios.py, urls/test_runs.py, urls/monitoring.py, urls/internal.py
│           │   ├── serializers/__init__.py
│           │   ├── services/runner.py, caller.py, judge.py, chat.py, quirks.py, metrics.py
│           │   ├── tasks/__init__.py
│           │   ├── authentication.py
│           │   ├── middleware.py
│           │   ├── throttling.py
│           │   └── management/commands/load_scenarios.py
│           └── email_pipeline/        # sidecar: LogicalThread, Message, ProcessedEvent
│
├── services/voice/                    # py3.12 / linux/amd64 (Daily SDK requirement)
│   ├── server.py                      # FastAPI: /connect (agent) + /caller/run (proxy to caller)
│   ├── pipeline.py                    # Agent pipeline: Daily→Silero VAD→Scribe v2→Haiku→11Labs
│   ├── caller_server.py               # FastAPI: /run → ScenarioCallerBot; /remote/connect + /remote/run → EvalAgent
│   ├── caller_bot.py                  # ScenarioCallerBot: virtual mic/speaker, TTS, Scribe, WAV
│   ├── eval_agent.py                  # Plain async: EvalAgent + EvalBridge + Scorer (no Pipecat infra)
│   ├── audio_utils.py                 # shared TTS + WAV utilities
│   ├── config.py                      # voice IDs, defaults
│   ├── Dockerfile                     # --platform=linux/amd64 python:3.12-slim
│   └── requirements.txt
│
├── services/web/                      # Next.js 14 UI
│   ├── app/agents/                    # agent list + detail (ElevenLabs gate)
│   ├── app/scenarios/                 # scenario list
│   ├── app/tests/                     # test run list + detail (transcript, scores, audio)
│   └── components/                    # elevenlabs-gate, runs-table, transcript, modals
│
├── cli/
│   ├── main.py                        # Typer: agents, scenarios, tests, calls
│   └── client.py                      # HTTP client, ShunyaError handling
│
├── scenarios/                         # YAML scenario files
├── recordings/                        # bind-mounted: caller writes WAVs, django serves them
└── docker-compose.yml                 # postgres, redis, django, celery_worker, pipecat, caller, web
```

---

---

# CALLER INTERFACE

Three callers are built. The test runner selects based on `TestRun.mode` and `agent.target_type`.

```python
# packages/agent/.../voice_qa/services/caller.py

class CallerInterface:
    def send(self, turn_text: str, conversation_id: str) -> dict: ...

class TextCaller(CallerInterface):
    """Strips Voice Quirks DSL, calls AgentChat (Claude Haiku) in-process."""
    def send(self, turn_text: str, conversation_id: str) -> dict:
        ...

class AudioCaller(CallerInterface):
    """Full-scenario (not turn-by-turn). Provisions a Daily room via the Pipecat
    server's /connect, then POSTs the whole scenario to /caller/run, which runs
    ScenarioCallerBot (ElevenLabs TTS in, Scribe v2 on the agent's audio out)."""
    def run_scenario(self, steps, conversation_id, recording_id="") -> list[dict]:
        ...
    def send(self, *a, **k):
        raise NotImplementedError("AudioCaller is full-scenario, not turn-by-turn.")

class RemoteAudioCaller(CallerInterface):
    """Full-scenario for ELEVENLABS agents. Calls /remote/connect + /remote/run
    on the caller service (:8002). EvalAgent drives the ElevenLabs ConvAI WS."""
    def run_scenario(self, steps, conversation_id, **kwargs) -> list[dict]:
        ...
    def send(self, *a, **k):
        raise NotImplementedError("RemoteAudioCaller is full-scenario, not turn-by-turn.")

def get_caller(mode, agent) -> CallerInterface:
    if agent.target_type == Agent.TargetType.ELEVENLABS:
        return RemoteAudioCaller(agent)
    return TextCaller(agent) if mode == "text" else AudioCaller(agent)
```

> The runner branches on mode + target_type: audio mode calls `caller.run_scenario()` (whole scenario handed to the bot); text mode loops `caller.send()` per step; remote mode delegates to the caller service's EvalAgent over the ElevenLabs Conversational AI WebSocket.

---

---

# BUILD ORDER

| Phase | What | Key files |
|---|---|---|
| 1 | Django foundation: models + migrations + RLS tenant setup + API key auth | `packages/mt/`, `voice_qa/models/`, `authentication.py` |
| 2 | Agent chat endpoint + DRF viewsets for all resources | `voice_qa/services/chat.py`, `voice_qa/views/`, `config/urls.py` |
| 3 | Pipecat voice agent: pipeline + Daily room lifecycle | `services/voice/server.py`, `services/voice/pipeline.py` |
| 4 | Text mode: YAML loader + TextCaller + Celery runner | `voice_qa/services/caller.py`, `voice_qa/services/runner.py`, `scenarios/` |
| 5 | LLM Judge: Claude rubric scoring + JudgeScore writes | `voice_qa/services/judge.py` |
| 6 | Audio fidelity mode: ScenarioCallerBot (separate caller service) | `services/voice/caller_server.py`, `services/voice/caller_bot.py` |
| 7 | Remote ElevenLabs agent mode: EvalAgent + EvalBridge + ScoringSubAgent | `services/voice/eval_agent.py`, `services/voice/caller_server.py` |
| 8 | Monitoring: post-call metrics + AlertConfig + webhook | `voice_qa/services/metrics.py`, `voice_qa/models/` |
| 9 | CLI: Typer control plane | `cli/` |
| 10 | Tests: pytest + RLS + live scoring + runner tests | `tests/` |
| 11 | Call recording + browser playback | `caller_bot.py`, `config/urls.py` (`_RecordingView`) |
| 12 | Web UI: Next.js | `services/web/` |

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
`/connect` mints a third, non-owner **observer token** and returns `observer_url = "{room_url}?t={token}"`; rooms are created with `max_participants: 10` to leave headroom for human observers. The runner calls `AudioCaller._connect()` *before* the scenario starts and persists the link to `TestRun.observer_url` (`URLField`). The CLI prints a join link during a `--wait` poll the moment the run reports `running`. This is per-run live monitoring; an aggregate "all calls" dashboard URL isn't possible because each call is its own ephemeral room.

### Daily bridge concurrency limit (remote mode)
`daily-python` allows only **one active `CallClient` per OS process**. The same constraint that forced the caller bot into its own process (separate from pipecat) also prevents two concurrent `EvalBridge` instances inside the caller process.

`eval_agent.py` enforces this with a module-level boolean flag `_daily_bridge_in_use`. If a second remote run starts while the first is running:
- The second run logs a warning and runs **WS-only** (ElevenLabs conversation still works; just no Daily live listen-in).
- The first run's room is completely unaffected.
- The flag is released in the `finally` block so the next sequential run gets the Daily relay.

**Why a boolean flag, not an asyncio.Lock?** uvicorn runs with 1 worker (no `--workers` flag in docker-compose), so all concurrent requests share one event loop. asyncio is cooperative multitasking — there is no parallelism between coroutines. A boolean is safe and simpler.

### WAV recording — virtual write cursor for agent audio
`ScenarioCallerBot` records the caller side by calling `write_frames` on a Daily virtual microphone device. Daily's SDK clocks these frames out in real-time (~20 ms chunks), so using `time.monotonic()` as the WAV offset is accurate.

`EvalAgent` records the agent side by capturing `audio` events from the ElevenLabs Conversational AI WebSocket. ElevenLabs streams all audio chunks for an agent utterance **as fast as the network allows** (typically 50–200 ms for an entire 3-second response). If each chunk is written at its arrival time, they all land at the same offset in the WAV and the entire utterance plays simultaneously (severe overlap).

**Fix:** `_agent_write_cursor` in `EvalAgent.__init__` (type `float`):
- Anchored to `time.monotonic() - self._call_start_ts` on the **first chunk of each agent turn** — this correctly places the turn at its real wall-clock position in the recording.
- Advanced by `len(pcm) / BYTES_PER_SEC` for **each subsequent chunk** — places chunks sequentially regardless of how fast they arrived over the network.
- NOT reset by `_reset_agent_turn()` — it persists across turns so inter-turn silence is preserved in the WAV.

### ElevenLabs ConvAI — silence keepalive strategy
ElevenLabs Conversational AI expects a continuous stream of `user_audio_chunk` WebSocket events (modelled on a live microphone). Sending nothing for several seconds produces an "Audio duration mismatch" warning and can desync their transcript player.

The keepalive sends `\x00` PCM silence frames. Its timing is critical:

| Window | Keepalive? | Why |
|---|---|---|
| Greeting collection | ❌ No | Agent is speaking; sending silence records user audio simultaneous with agent greeting → overlap in EL transcript |
| TTS synthesis (0.5–2s) | ✅ Yes | No real audio is available; fills the gap to prevent desync |
| Scoring API call (1–3s) | ✅ Yes | Same — inter-turn dead time from the user's perspective |
| Agent response window | ❌ No | Agent is speaking; silence here causes EL to record user audio over the agent track, showing overlap in their playback visualizer |
| Caller speech transmission | ❌ No | Real audio being sent; keepalive would interleave silence frames between speech frames, scrambling pacing |

Implementation lives in `_speak_loop()` in `eval_agent.py` — one keepalive task (`_kp`) that starts/stops at precisely these transition points.

**Remaining limitation:** The gap during agent response (~5–10s with no user audio) still triggers the "Audio duration mismatch" warning. This is the unavoidable trade-off for correct transcript playback. Our WAV recording is the authoritative record.

### Concurrency limits
- **Pipecat `/connect`**: max 5 concurrent pipelines (returns 429 beyond that).
- **Caller `/remote/run`**: max 4 concurrent remote EvalAgent runs (returns 429 beyond that).
- **EvalBridge (Daily relay)**: max 1 active per caller process (enforced by `_daily_bridge_in_use` flag).
