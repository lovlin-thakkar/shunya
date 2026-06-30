# Shunya — Architecture & Developer Guide

Shunya is a **voice-AI QA platform**. You point it at a conversational agent (the "agent
under test"), hand it a scenario, and it drives a full conversation — over text *or* real
WebRTC audio *or* deployed ElevenLabs Conversational AI agents — then has an LLM judge
score the transcript against a rubric.

This document explains how the pieces fit together, how data flows through a test run, and
where to find things in the codebase. For operational steps see `RUNBOOK.md`; for the deep
audio-mode engineering notes see `TECH_SPEC.md`.

---

## 1. The Big Picture

There are **four** moving parts: one control plane, two voice processes, a CLI, and a web UI.

```
                                  ┌─────────────────────────────────────────────┐
                                  │                  YOU / CLIENT                 │
                                  │   shunya CLI  ·  curl  ·  Next.js UI         │
                                  └───────────────────────┬─────────────────────-┘
                                                           │  HTTPS + Api-Key
                                                           ▼
 ┌────────────────────────────────────────────────────────────────────────────────────────┐
 │  DJANGO API  (control plane · :8000 · DRF · multi-tenant via RLS)                       │
 │                                                                                          │
 │   voice_qa          ─ Agent, Scenario, TestRun, TestResult, JudgeScore, Call, ...         │
 │   multitenant       ─ Tenant, TenantAPIKey, ActivityTenantBaseModel, middlewares          │
 │   email_pipeline    ─ LogicalThread, Message, ... (sidecar app)                           │
 │                                                                                          │
 │        ┌──────────────┐         enqueue          ┌─────────────────────────────┐         │
 │        │  DRF views    │ ──────────────────────▶ │  Redis (broker + result)    │        │
 │        └──────────────┘                          └──────────────┬──────────────┘         │
 │                                                                 │ consume                 │
 │        ┌──────────────────────────────────────────────────────▼──────────────┐          │
 │        │  CELERY WORKER   run_scenario_task  ·  run_judge_task                 │          │
 │        │                  compute_call_metrics  ·  alert rollups               │          │
 │        └───────┬──────────────────────────────────────────────┬──────────────-┘          │
 └────────────────┼──────────────────────────────────────────────┼─────────────────────────┘
                  │                                               │
       TEXT MODE  │ in-process                    AUDIO / REMOTE  │ HTTP
                  ▼                               MODES           ▼
       ┌────────────────────┐        ┌──────────────────────────────────────────────┐
       │ AgentChat (Haiku)  │        │  PIPECAT AGENT SERVER  (:8001 · FastAPI)       │
       │ services/chat.py   │        │  server.py → pipeline.py                       │
       │ stateful per        │        │  the AGENT UNDER TEST pipeline (BUILTIN):      │
       │ conversation_id     │        │   Scribe v2 STT → Claude Haiku → 11Labs TTS    │
       └────────────────────┘        └───────────────────┬──────────────────────────┘
                                                         │ POST /run (separate proc)
                                                         ▼
                                     ┌──────────────────────────────────────────────┐
                                     │  CALLER SERVICE  (:8002 · FastAPI)             │
                                     │  caller_server.py → caller_bot.py              │
                                     │  ScenarioCallerBot (BUILTIN audio mode):        │
                                     │   11Labs TTS out (virtual mic)                 │
                                     │   Scribe v2 on agent audio (virtual speaker)   │
                                     │   writes /recordings/<run-id>.wav              │
                                     │                                                │
                                     │  EvalAgent (ELEVENLABS remote mode):            │
                                     │   WorkerRunner + BaseWorker framework           │
                                     │   Connect to ElevenLabs ConvAI WebSocket       │
                                     │   Drive scenario steps, concurrent scoring     │
                                     │   Post live scores to Django                   │
                                     └───────┬──────────────────────────┬────────────┘
                                             │                          │
                        ┌────────────────────▼─────────┐   ┌───────────▼───────────┐
                        │   DAILY.CO WebRTC room         │   │ ElevenLabs ConvAI WS  │
                        │   (bot ↔ bot, audio mode)      │   │ (remote agent mode)   │
                        └────────────────────────────────┘   └───────────────────────┘
```

**Why two voice processes?** `daily-python` allows only one `CallClient` / `Daily.init()`
per OS process. The agent and the synthetic caller each need their own, so they live in
separate FastAPI services (`:8001` agent, `:8002` caller).

**Three test modes:**

| Mode | Target | CallerInterface | Voice Runtime |
|------|--------|----------------|---------------|
| `text` | BUILTIN (in-process Haiku) | `TextCaller` | None — in-process |
| `audio` | BUILTIN (Pipecat pipeline) | `AudioCaller` | Pipecat :8001 + Caller :8002 |
| `remote` | ELEVENLABS (ConvAI agent) | `RemoteAudioCaller` | Caller :8002 — EvalAgent |

---

## 2. Services at a Glance

| Service          | Process / Port      | Entry point                       | Role                                                            |
|------------------|---------------------|-----------------------------------|----------------------------------------------------------------|
| **Django API**   | `:8000`             | `apps/api/src/zenapi/config/`     | Multi-tenant REST control plane (RLS); serves `/recordings/*.wav` |
| **Celery worker**| —                   | `packages/agent/.../voice_qa/tasks/` | Runs scenarios + LLM judge + metric/alert computation; NOT auto-reloaded |
| **Pipecat agent**| `:8001`             | `services/voice/server.py`        | The voice **agent under test** pipeline                         |
| **Caller bot**   | `:8002`             | `services/voice/caller_server.py` | The synthetic **caller** (`ScenarioCallerBot` + `EvalAgent`)   |
| **Web UI**       | `:3000`             | `services/web/`                   | Next.js frontend for agents, scenarios, test runs               |
| **CLI**          | local               | `cli/main.py`                     | Thin wrapper over the REST API (`shunya …`)                     |
| Postgres / Redis | `:5432` / `:6379`   | docker-compose                    | Single-schema RLS DB; Celery broker + result backend           |

`docker-compose up` brings the whole stack up. The voice services are pinned to
`python:3.12` on `linux/amd64` (daily-python has no 3.14 wheels and misbehaves on ARM64).

---

## 3. Data Flow — A Test Run, End to End

This is the spine of the system. Follow it once and the codebase makes sense.

```
1.  POST /api/v1/test-runs/  {agent_id, scenario_id, mode}
        └─▶ voice_qa/views/__init__.py  creates TestRun (status=running)
            └─▶ dispatches run_scenario_task(test_run_id, tenant_id)
                                                          ▲
                                  tenant_id is REQUIRED — the worker must set
                                  context.current_tenant before any DB access,
                                  or RLS filters everything out.

2.  run_scenario_task  (voice_qa/tasks/__init__.py)
        └─▶ runner.run_scenario()  (voice_qa/services/runner.py)
            └─▶ picks a CallerInterface based on mode + agent.target_type:

    ── TEXT MODE (BUILTIN agent) ─────────────────────────────────────────
        TextCaller.send(step)            (voice_qa/services/caller.py)
          • strip_quirks() removes Voice Quirks DSL ([pause:3s], [stutter], …)
          • extract_quirk_tags() records them in the transcript
          • AgentChat.send()  →  Claude Haiku, in-process, stateful per conversation_id
        returns {response, ts_ms} for each step

    ── AUDIO MODE (BUILTIN agent) ─────────────────────────────────────────
        AudioCaller._connect() then .run_scenario(recording_id=run.id)
          • POST :8001 /connect      → pipecat provisions the Daily room + starts the AGENT
                                       pipeline; returns observer_url (pre-authed Daily join
                                       link, room max_participants: 10) → persisted to
                                       TestRun.observer_url so a human can listen in live
          • POST :8001 /caller/run   → waits for agent TTS readiness, then
              → POST :8002 /run      → ScenarioCallerBot joins the same Daily room
          • caller speaks each step via 11Labs TTS (virtual mic);
            captures agent audio via virtual speaker + Scribe v2 STT
          • writes /recordings/<run-id>.wav  (mono 16 kHz, both sides mixed)

    ── REMOTE MODE (ELEVENLABS agent) ────────────────────────────────────
        RemoteAudioCaller.run_scenario(steps, conversation_id, ...)
          • POST :8002 /remote/connect  → provisions Daily room for observer access
          • POST :8002 /remote/run      → EvalAgent (WorkerRunner) connects to
            ElevenLabs Conversational AI WebSocket, drives scenario steps
          • After each agent turn: concurrent ScoringSubAgent instances score
            the partial transcript via Claude Haiku
          • Posts live scores to Django via POST /internal/test-runs/{id}/live-scores/
          • Writes /recordings/<run-id>.wav

3.  After all scenario steps complete — Tier 1 evaluation:
        └─▶ runner._evaluate_assertions()  (synchronous, heuristics)
            • Checks known assertion names: resolved_within_5_turns,
              agent_acknowledges_frustration, etc.
            • Semantic assertions (no_hallucinated_policy) always pass heuristically
            • Results stored in TestResult.assertion_results

4.  runner creates TestResult (the full transcript)
        └─▶ dispatches run_judge_task(test_result_id, rubric, tenant_id)

5.  run_judge_task  (voice_qa/tasks/__init__.py)
        └─▶ judge.evaluate_result()  (voice_qa/services/judge.py)
            • Claude Sonnet scores the transcript 0.0–1.0 per rubric field
            • pass threshold is >= 0.7  →  verdict: Success / Partial / Failed
            └─▶ writes JudgeScore rows; updates TestRun status → completed

6.  Client polls GET /api/v1/test-runs/<id>/  (or `shunya tests run … --wait`)
        └─▶ reads back TestResult + JudgeScores + assertion_results + live_scores
        └─▶ audio runs: GET /recordings/<run-id>.wav   (shunya tests audio <run-id>)
        └─▶ live listen-in: once status=running, --wait prints TestRun.observer_url
            (per-run ephemeral Daily room — open it to hear the call in real time)
```

### Internal endpoints (Pipecat → Django only)

The voice pipeline reports turns back to Django over `/internal/` routes (service-to-service,
authenticated by `X-Service-Token` + `X-Tenant-Id`):

```
POST /internal/calls/start/              ← pipeline.py: a call began
POST /internal/calls/{id}/turn/          ← each STT/LLM/TTS turn appended to Transcript
POST /internal/calls/{id}/end/           ← call finished; finalize Call + compute metrics (Celery)
POST /internal/test-runs/{id}/live-scores/  ← EvalAgent posts live scores during remote runs
```

Handlers live in `packages/agent/src/zenlib_agentos/zenlib/reusable_apps/voice_qa/urls/internal.py` (routed from `apps/api/src/zenapi/config/urls.py`).

---

## 3b. Joining a Daily Call Manually (two paths)

There are two ways a human can get into the live Daily.co room. They are different — one is
passive, one is interactive.

```
                          ┌─────────────────────────────────────────────────────────┐
                          │            Daily.co WebRTC room (max 10 seats)            │
                          └─────────────────────────────────────────────────────────┘
        PATH A — LISTEN IN                          PATH B — TALK TO THE AGENT
        (passive, during a test run)                (interactive, ad-hoc)
   ┌──────────────────────────────┐          ┌──────────────────────────────────────┐
   │ agent bot  ◀──▶  caller bot   │          │ agent bot  ◀──▶  YOU (mic)             │
   │            you = silent ear   │          │            no synthetic caller         │
   └──────────────────────────────┘          └──────────────────────────────────────┘
```

### Path A — Listen in on a running test (passive)

During an **audio-mode test run**, `/connect` mints an `observer_url` (a pre-authed Daily
join link). The runner persists it to `TestRun.observer_url`, and
`shunya tests run … --wait` prints it once the run reaches `running`. Open it
to **hear** the synthetic caller ↔ agent conversation as it happens.

### Path B — Talk to the agent yourself (interactive manual test)

A dedicated endpoint starts **only the agent pipeline — no synthetic caller** — and returns a
join link:

```
POST /api/v1/agents/<agent-id>/connect/        (voice_qa/views/ → pipecat /connect)
  → provisions a Daily room, boots Scribe v2 → Haiku → 11Labs TTS (the agent)
  → returns { room_url, caller_token, observer_url }
```

CLI wrapper:

```bash
shunya agents connect <agent-id>            # opens the join link in your browser
shunya agents connect <agent-id> --no-open  # just print the link
```

Requires the **pipecat** voice server (`:8001`) to be up. The **caller** service (`:8002`) is
NOT needed here — there's no synthetic caller in this path.

| | Path A — Listen in | Path B — Talk to it |
|---|---|---|
| Trigger        | audio-mode test run                | `shunya agents connect <id>`         |
| Synthetic caller | yes (drives the convo)           | no — you drive it                    |
| Your role      | silent observer                    | the caller (mic on)                  |
| Services needed | pipecat :8001 + caller :8002      | pipecat :8001 only                   |
| Scored / saved | yes (TestResult, JudgeScore, .wav) | no (ad-hoc, not recorded)            |

---

## 4. Multi-Tenancy (read this before touching the DB)

Shunya uses **`zenlib-mt-py`** with **RLS single-schema** on Postgres — NOT `django-tenants`.

```
SINGLE schema (public)
───────────────────────
all tables, all tenants → isolated by Postgres RLS on tenant_id
```

- **Engine:** Every tenant-scoped model inherits `ActivityTenantBaseModel` which adds a `tenant` FK, auto-populated from `context.current_tenant` ContextVar.
- **RLS policies** are applied automatically on `post_migrate` — two policies per table:
  - `multitenant_rls__current_tenant_only`: `current_setting('app.current_tenant_id')::int = tenant_id`
  - `multitenant_rls__cross_tenant`: escape hatch for admin/migrations
- **Middleware stack** (order is critical):
  1. `MultitenantContextMiddleware` — resolves tenant from Knox token or `X-Tenant-Id`/`X-Service-Token` header, sets `context.current_tenant` ContextVar
  2. `TenantAPIKeyMiddleware` — validates `Authorization: Api-Key <key>`, sets `context.current_tenant` for CLI callers
  3. `MultitenantRLSMiddleware` — reads the ContextVar, runs `SET LOCAL app.current_tenant_id = <id>` on the DB connection
- **`ATOMIC_REQUESTS = True`** ensures `SET LOCAL` scopes correctly per request.
- **Celery + RLS:** Tasks take `tenant_id` (integer PK) and call `context.current_tenant.set(tenant)` before any ORM access. This is the #1 source of empty results — see the call-out in the data-flow diagram above. Always dispatch with `tenant.id`.

**Auth mechanisms:**

| Method | Header | Authenticator | Used by |
|--------|--------|---------------|---------|
| Knox token | `Authorization: Token <token> <tenant_id>` | `TokenAuthentication` | Web UI |
| API key | `Authorization: Api-Key <raw_key>` | `TenantAPIKeyAuthentication` | CLI, curl |
| Service token | `X-Service-Token` + `X-Tenant-Id` | `ServiceTokenAuthentication` | Pipecat → Django internal |

---

## 5. Codebase Map — What Goes Where

```
zenerate/web-py/
├── docker-compose.yml          # the whole stack: postgres, redis, django, celery_worker, pipecat, caller, web
├── CLAUDE.md                   # agent/contributor instructions (authoritative quick reference)
├── PRD.md / PLAN.md            # product requirements + build plan
├── TECH_SPEC.md                # deep audio-mode engineering notes + data models
├── RUNBOOK.md                  # operational how-to (start/stop, debug, env)
├── DOCS.md                     # ← you are here (architecture + dev guide)
│
├── apps/api/                   # ── CONTROL PLANE (Django) ──────────────────────────────────
│   ├── manage.py
│   ├── pyproject.toml          # uv workspace member
│   ├── src/zenapi/
│   │   └── config/
│   │       ├── settings/__init__.py  # single-file settings (middleware wired, RLS-ready)
│   │       ├── urls.py               # root: mounts urls, voice, email, internal, recordings
│   │       └── url_confs/
│   │           ├── urls.py           # base (health, auth, admin)
│   │           ├── voice.py          # mounts voice_qa sub-routers under /api/v1/
│   │           └── email.py          # mounts email_pipeline under /api/v1/email/
│   ├── celery.py                # Celery app (zenapi.celery), Redis broker/backend
│   └── tests/                   # pytest suite
│       ├── conftest.py          # tenant_a, tenant_b, in_tenant, api_key_headers, service_headers
│       ├── factories.py         # TenantFactory
│       └── test_*.py            # multitenant, voice_qa, caller, runner, tasks, live_scoring, ...
│
├── packages/                    # ── SHARED PYTHON PACKAGES (uv workspace) ────────────────
│   │
│   ├── mt/                      # zenlib-mt-py — MULTITENANCY LIBRARY (DO NOT MODIFY)
│   │   └── src/zenlib/
│   │       ├── reusable_apps/multitenant/
│   │       │   ├── models.py         # Tenant, ActivityTenantBaseModel
│   │       │   ├── context.py        # current_tenant ContextVar
│   │       │   ├── middleware.py     # MultitenantContextMiddleware, MultitenantRLSMiddleware
│   │       │   ├── managers.py       # AutoFilteringManager
│   │       │   └── settings.py
│   │       └── django_utils/db/pg_rls/
│   │           └── policies.py       # RLS policy builders, post_migrate signals
│   │
│   └── agent/                    # zenlib-agent-py — VOICE QA PACKAGE
│       └── src/zenlib_agentos/zenlib/reusable_apps/
│           ├── voice_qa/               # ★ the core of the product
│           │   ├── apps.py
│           │   ├── models/__init__.py  # Agent, Call, Transcript, CallMetric, Scenario,
│           │   │                       # TestRun, TestResult, JudgeScore, AlertConfig, etc.
│           │   ├── views/__init__.py   # DRF viewsets: Agent, Call, Scenario, TestRun, Alert
│           │   ├── serializers/
│           │   ├── urls/               # agents, scenarios, test_runs, monitoring, internal
│           │   ├── services/
│           │   │   ├── runner.py       # run_scenario() orchestrator; _check_assertion()
│           │   │   ├── caller.py       # TextCaller, AudioCaller, RemoteAudioCaller; quirks DSL
│           │   │   ├── judge.py        # Claude Sonnet rubric scoring
│           │   │   ├── chat.py         # AgentChat — Claude Haiku, in-process
│           │   │   ├── quirks.py       # Voice Quirks DSL parsing
│           │   │   └── metrics.py      # post-call metrics + alert evaluation
│           │   ├── tasks/__init__.py   # Celery: run_scenario_task, run_judge_task, compute_call_metrics
│           │   ├── authentication.py   # TenantAPIKeyAuthentication, ServiceTokenAuthentication
│           │   ├── middleware.py       # TenantAPIKeyMiddleware
│           │   └── management/commands/  # load_scenarios
│           │
│           └── email_pipeline/         # sidecar app (LogicalThread, Message, etc.)
│
├── services/voice/              # ── VOICE RUNTIME (Python 3.12 / linux-amd64) ───────
│   ├── server.py                # :8001 AGENT — /connect, /caller/run, /health
│   ├── pipeline.py              # run_voice_agent(): Scribe v2 STT → Haiku → 11Labs TTS
│   ├── caller_server.py         # :8002 CALLER — /run, /remote/connect, /remote/run, /health
│   ├── caller_bot.py            # ScenarioCallerBot; mixes both sides → mono 16kHz WAV
│   ├── eval_agent.py            # EvalAgent (BaseWorker), EvalBridge, ScoringSubAgent
│   ├── audio_utils.py           # TTS + WAV recording utilities
│   ├── config.py                # voice IDs, model names, defaults
│   ├── Dockerfile
│   └── requirements.txt
│
├── services/web/               # ── NEXT.JS WEB UI ───────────────────────────────────
│   ├── app/
│   │   ├── agents/             # agent list + detail pages
│   │   ├── scenarios/          # scenario list page
│   │   └── tests/              # test run list + detail/transcript pages
│   ├── components/             # elevenlabs-gate, runs-table, transcript, modals
│   └── lib/                    # api client, types
│
├── cli/                        # ── shunya CLI (Typer) ──────────────────────────────
│   ├── main.py                 # commands: agents / scenarios / tests / calls
│   └── client.py               # HTTP client (reads SHUNYA_API_KEY, SHUNYA_BASE_URL)
│
├── scenarios/                  # scenario YAML (load_scenarios syncs → DB)
│   └── *.yaml                  # angry_customer_refund, booking_happy_path, …
│
└── recordings/                 # generated <run-id>.wav files (audio-mode output)
```

### Quick "where do I…?" index

| I want to…                                   | Go to                                                            |
|----------------------------------------------|-----------------------------------------------------------------|
| Change how a scenario is driven / orchestrated | `packages/agent/.../voice_qa/services/runner.py`               |
| Add/modify a Voice Quirks DSL tag            | `packages/agent/.../voice_qa/services/caller.py` (quirks) + `quirks.py` |
| Tune the rubric scoring or pass threshold    | `packages/agent/.../voice_qa/services/judge.py`                |
| Change the agent's brain (text mode)         | `packages/agent/.../voice_qa/services/chat.py` (`AgentChat`)   |
| Change the voice pipeline (STT/LLM/TTS)      | `services/voice/pipeline.py`                                     |
| Change the synthetic caller's behavior       | `services/voice/caller_bot.py` (`ScenarioCallerBot`)            |
| Change remote EL agent eval behavior         | `services/voice/eval_agent.py` (`EvalAgent`, `ScoringSubAgent`) |
| Talk to an agent live in a browser           | `shunya agents connect <id>` → `POST /api/v1/agents/<id>/connect/` |
| Add a REST endpoint                          | relevant `voice_qa/views/__init__.py` + `voice_qa/urls/`       |
| Add a Celery task                            | `voice_qa/tasks/__init__.py` (remember the `tenant_id` arg!)   |
| Add a model / migrate                        | `voice_qa/models/__init__.py` → `uv run python manage.py makemigrations && migrate` |
| Add a CLI command                            | `cli/main.py` (+ `cli/client.py` for new HTTP calls)            |
| Touch tenant routing / API keys              | `voice_qa/authentication.py`, `voice_qa/middleware.py`          |
| Serve / locate a call recording             | `config/urls.py` (`_RecordingView`); files in `recordings/`    |

---

## 6. Domain Glossary

| Term                  | Meaning                                                                          |
|-----------------------|----------------------------------------------------------------------------------|
| **Agent under test**  | The conversational AI Shunya is QA-ing (BUILTIN via Pipecat, ELEVENLABS via ConvAI WS) |
| **Scenario**          | A persona + ordered `steps` + `assertions` + optional `rubric` (YAML → DB)        |
| **Voice Quirks DSL**  | Inline step annotations (`[stutter]`, `[pause:3s]`, `[hard_input:"…"]`, …)         |
| **TestRun**           | One execution of a scenario against an agent in a mode (`text`/`audio`/`remote`)   |
| **TestResult**        | The transcript + verdict produced by a TestRun                                    |
| **JudgeScore**        | Per-rubric-field score (0.0–1.0) from the Claude Sonnet judge; pass ≥ 0.7          |
| **Live Score**        | Per-turn provisional score from ScoringSubAgents during remote runs               |
| **CallerInterface**   | Abstraction the runner uses; `TextCaller`, `AudioCaller`, or `RemoteAudioCaller`   |
| **ScenarioCallerBot** | Synthetic caller for BUILTIN audio mode; joins Daily room, speaks steps            |
| **EvalAgent**         | Pipecat WorkerRunner-based orchestrator for ELEVENLABS remote agent testing       |
| **ScoringSubAgent**   | Concurrent Pipecat sub-agent that scores one rubric field per turn (live)         |

---

## 7. Models (LLM usage)

| Use                         | Model                          | Where                       |
|-----------------------------|--------------------------------|-----------------------------|
| Agent brain (under test)    | `claude-haiku-4-5-20251001`    | `voice_qa/services/chat.py`, pipeline |
| Live scorer (remote mode)   | `claude-haiku-4-5-20251001`    | `services/voice/eval_agent.py` |
| LLM judge (rubric scoring)  | `claude-sonnet-4-6`            | `voice_qa/services/judge.py` |
| STT (audio mode)            | ElevenLabs **Scribe v2**       | `services/voice/pipeline.py`, `caller_bot.py` |
| TTS (audio mode)            | ElevenLabs                     | `services/voice/pipeline.py`, `caller_bot.py`, `eval_agent.py` |

---

## 8. Gotchas Worth Repeating

- **Celery worker does not auto-reload.** After editing `runner.py`, `judge.py`, or any task:
  `docker-compose restart celery_worker`. (Django, pipecat, caller all run `--reload`.)
- **Always pass `tenant_id` to tasks** — omitting it ⇒ RLS filters everything out (empty results).
- **Two voice processes are intentional** — one `CallClient` per process limit.
- **ElevenLabs TTS `output_format` is a query param**, not a body field (else MP3 → VAD noise).
- **Empty `voice_id` ⇒ opaque 403** — always `voice_id or DEFAULT`.
- **5 concurrent pipeline limit** on pipecat `/connect`, **4 concurrent remote runs** on caller.
- See `TECH_SPEC.md` for the full audio-mode engineering notes (VAD ordering, thread affinity).
