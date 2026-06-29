# Shunya — Architecture & Developer Guide

Shunya is a **voice-AI QA platform**. You point it at a conversational agent (the "agent
under test"), hand it a scenario, and it drives a full conversation — over text *or* real
WebRTC audio — then has an LLM judge score the transcript against a rubric.

This document explains how the pieces fit together, how data flows through a test run, and
where to find things in the codebase. For operational steps see `RUNBOOK.md`; for the deep
audio-mode engineering notes see `TECH_SPEC.md`.

---

## 1. The Big Picture

There are **four** moving parts: one control plane, two voice processes, and a CLI.

```
                                  ┌─────────────────────────────────────────────┐
                                  │                  YOU / CLIENT                 │
                                  │   shunya CLI  ·  curl  ·  any REST client     │
                                  └───────────────────────┬─────────────────────-┘
                                                           │  HTTPS + X-API-Key
                                                           │  Host: <tenant>.localhost
                                                           ▼
 ┌────────────────────────────────────────────────────────────────────────────────────────┐
 │  DJANGO API  (control plane · :8000 · DRF · multi-tenant via django-tenants)             │
 │                                                                                          │
 │   apps.tenants     ─ public schema: Tenant, Domain, TenantAPIKey (SHA-256), routing      │
 │   apps.agents      ─ Agent, Call, Transcript, CallMetric  +  AgentChat (Haiku brain)     │
 │   apps.testing     ─ Scenario, TestRun, TestResult, JudgeScore  +  runner / judge / DSL  │
 │   apps.monitoring  ─ AlertConfig, AlertEvent, metrics rollups                            │
 │   config           ─ settings, celery, urls, /recordings/<id>.wav file server           │
 │                                                                                          │
 │        ┌──────────────┐         enqueue          ┌─────────────────────────────┐         │
 │        │  DRF views    │ ───────────────────────▶ │  Redis (broker + result)    │        │
 │        └──────────────┘                          └──────────────┬──────────────┘         │
 │                                                                 │ consume                 │
 │        ┌──────────────────────────────────────────────────────▼──────────────┐          │
 │        │  CELERY WORKER   run_scenario_task  ·  run_judge_task                 │          │
 │        │                  (beat → monitoring/alert rollups)                    │          │
 │        └───────┬──────────────────────────────────────────────┬──────────────-┘          │
 └────────────────┼──────────────────────────────────────────────┼─────────────────────────┘
                  │                                               │
       TEXT MODE  │ in-process                          AUDIO MODE│ HTTP /connect, /caller/run
                  ▼                                               ▼
       ┌────────────────────┐                ┌──────────────────────────────────────────────┐
       │ AgentChat (Haiku)  │                │  PIPECAT AGENT SERVER  (:8001 · FastAPI)       │
       │ apps/agents/chat.py│                │  server.py → pipeline.py                       │
       │ stateful per        │               │  the AGENT UNDER TEST pipeline:                │
       │ conversation_id     │               │   Scribe v2 STT → Claude Haiku → 11Labs TTS    │
       └────────────────────┘                └───────────────────┬──────────────────────────┘
                                                                 │ POST /run (separate proc:
                                                                 │ daily-python = 1 CallClient)
                                                                 ▼
                                             ┌──────────────────────────────────────────────┐
                                             │  CALLER SERVICE  (:8002 · FastAPI)             │
                                             │  caller_server.py → caller_bot.py              │
                                             │  ScenarioCallerBot = the SYNTHETIC CALLER:     │
                                             │   11Labs TTS out (virtual mic)                 │
                                             │   Scribe v2 on agent audio (virtual speaker)   │
                                             │   writes /recordings/<run-id>.wav (mono 16kHz) │
                                             └───────────────────┬──────────────────────────┘
                                                                 │
                                       ┌─────────────────────────▼─────────────────────────┐
                                       │   DAILY.CO  WebRTC room  (both bots join it)        │
                                       │   agent audio  ◀───────────────────────▶  caller    │
                                       └─────────────────────────────────────────────────────┘
```

**Why two voice processes?** `daily-python` allows only one `CallClient` / `Daily.init()`
per OS process. The agent and the synthetic caller each need their own, so they live in
separate FastAPI services (`:8001` agent, `:8002` caller).

---

## 2. Services at a Glance

| Service          | Process / Port      | Entry point                       | Role                                                            |
|------------------|---------------------|-----------------------------------|----------------------------------------------------------------|
| **Django API**   | `:8000`             | `django_api/config/`              | Multi-tenant REST control plane; serves `/recordings/*.wav`     |
| **Celery worker**| —                   | `django_api/apps/*/tasks.py`      | Runs scenarios + LLM judge; NOT auto-reloaded                   |
| **Celery beat**  | —                   | `config/celery.py`                | Schedules monitoring/alert rollups                              |
| **Pipecat agent**| `:8001`             | `pipecat_agent/server.py`         | The voice **agent under test** pipeline                         |
| **Caller bot**   | `:8002`             | `pipecat_agent/caller_server.py`  | The synthetic **caller** (`ScenarioCallerBot`)                  |
| **CLI**          | local               | `cli/main.py`                     | Thin wrapper over the REST API (`shunya …`)                     |
| Postgres / Redis | `:5432` / `:6379`   | docker-compose                    | Schema-per-tenant DB; Celery broker + result backend           |

`docker-compose up` brings the whole stack up. The voice services are pinned to
`python:3.12` on `linux/amd64` (daily-python has no 3.14 wheels and misbehaves on ARM64).

---

## 3. Data Flow — A Test Run, End to End

This is the spine of the system. Follow it once and the codebase makes sense.

```
1.  POST /api/test-runs/  {agent_id, scenario, mode}
        └─▶ apps/testing/views.py  creates TestRun (status=running)
            └─▶ dispatches run_scenario_task(test_run_id, schema_name=connection.schema_name)
                                                          ▲
                                  schema_name is REQUIRED — the worker must re-enter the
                                  tenant's Postgres schema before any DB access, or you get
                                  "relation does not exist" (worker defaults to public).

2.  run_scenario_task  (apps/testing/tasks.py)
        └─▶ runner.run_scenario()  (apps/testing/runner.py)
            └─▶ picks a CallerInterface based on mode:

    ── TEXT MODE ────────────────────────────────────────────────────────────────
        TextCaller.send(step)            (apps/testing/caller.py)
          • strip_quirks() removes Voice Quirks DSL ([pause:3s], [stutter], …)
          • extract_quirk_tags() records them in the transcript
          • AgentChat.send()  →  Claude Haiku, in-process, stateful per conversation_id

    ── AUDIO MODE ───────────────────────────────────────────────────────────────
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

3.  After all scenario steps complete:
        └─▶ runner creates TestResult (the full transcript)
            └─▶ dispatches run_judge_task(test_result_id, rubric, schema_name)

4.  run_judge_task  (apps/testing/tasks.py)
        └─▶ judge.evaluate_result()  (apps/testing/judge.py)
            • Claude Sonnet scores the transcript 0.0–1.0 per rubric field
            • pass threshold is >= 0.7
            └─▶ writes JudgeScore rows; updates TestRun status → passed/failed

5.  Client polls GET /api/test-runs/<id>/  (or `shunya tests run … --wait`)
        └─▶ reads back TestResult + JudgeScores + transcript
        └─▶ audio runs: GET /recordings/<run-id>.wav   (shunya tests audio <run-id>)
        └─▶ live listen-in: once status=running, --wait prints TestRun.observer_url
            (per-run ephemeral Daily room — open it to hear the call in real time)
```

### Internal endpoints (Pipecat → Django only)

The voice pipeline reports turns back to Django over `/internal/` routes (NOT tenant-scoped,
not API-key auth — service-to-service):

```
POST /internal/calls/start/        ← pipeline.py _notify_django(): a call began
POST /internal/calls/{id}/turn/    ← each STT/LLM/TTS turn is appended to the Transcript
POST /internal/calls/{id}/end/     ← call finished; finalize Call + CallMetric
```

Handlers live in `apps/agents/internal_views.py` (routed by `apps/agents/internal_urls.py`).

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
join link). The runner persists it to `TestRun.observer_url` (`apps/testing/runner.py`), and
`shunya tests run … --wait` prints it once the run reaches `running` (`cli/main.py`). Open it
to **hear** the synthetic caller ↔ agent conversation as it happens. The synthetic caller is
driving the conversation — you're a silent observer.

### Path B — Talk to the agent yourself (interactive manual test)

A dedicated endpoint starts **only the agent pipeline — no synthetic caller** — and returns a
join link. Open it, unmute, and you are the caller:

```
POST /api/agents/<agent-id>/connect/        (apps/agents/views.py → pipecat /connect)
  → provisions a Daily room, boots Scribe v2 → Haiku → 11Labs TTS (the agent)
  → returns { room_url, caller_token, observer_url }
```

CLI wrapper:

```bash
shunya agents connect <agent-id>            # opens the join link in your browser
shunya agents connect <agent-id> --no-open  # just print the link
```

Requires the **pipecat** voice server (`:8001`) to be up. The **caller** service (`:8002`) is
NOT needed here — there's no synthetic caller in this path. No Celery, no `TestRun`, no judge:
this is a raw, un-scored conversation for eyeballing the agent's behavior.

| | Path A — Listen in | Path B — Talk to it |
|---|---|---|
| Trigger        | audio-mode test run                | `shunya agents connect <id>`         |
| Synthetic caller | yes (drives the convo)           | no — you drive it                    |
| Your role      | silent observer                    | the caller (mic on)                  |
| Services needed | pipecat :8001 + caller :8002      | pipecat :8001 only                   |
| Scored / saved | yes (TestResult, JudgeScore, .wav) | no (ad-hoc, not recorded)            |

---

## 4. Multi-Tenancy (read this before touching the DB)

Shunya uses **`django-tenants`** with **schema-per-tenant** on Postgres.

```
PUBLIC schema                         TENANT schema  (e.g. "demo")
──────────────                        ───────────────────────────
apps.tenants                          apps.agents     (Agent, Call, Transcript, CallMetric)
  Tenant, Domain                      apps.testing    (Scenario, TestRun, TestResult, JudgeScore)
  TenantAPIKey (SHA-256 hashed)       apps.monitoring (AlertConfig, AlertEvent)
```

- **Routing:** `TenantMainMiddleware` resolves the tenant from the request domain
  (`Host: demo.localhost`). Every CLI call needs `SHUNYA_TENANT_HOST`.
- **Auth:** Custom `TenantAPIKey` (in the public schema), *not* DRF's built-in API-key model.
  The `HasAPIKey` permission is DRF's, but authentication happens in the **view layer**
  (`apps/tenants/permissions.py`).
- **Celery + schemas:** Tasks always take `schema_name` and set `schema_context` before any
  DB access. This is the #1 source of `ProgrammingError: relation does not exist` — see the
  call-out in the data-flow diagram above. Always dispatch with
  `schema_name=connection.schema_name`.

---

## 5. Codebase Map — What Goes Where

```
Shunya/
├── docker-compose.yml          # the whole stack: postgres, redis, django, celery x2, pipecat, caller
├── CLAUDE.md                   # agent/contributor instructions (authoritative quick reference)
├── PRD.md / PLAN.md            # product requirements + build plan
├── TECH_SPEC.md                # deep audio-mode engineering notes
├── RUNBOOK.md                  # operational how-to (start/stop, debug, env)
├── DOCS.md                     # ← you are here (architecture + dev guide)
│
├── django_api/                 # ── CONTROL PLANE ──────────────────────────────────
│   ├── manage.py
│   ├── config/                 # project config (NOT a Django "app")
│   │   ├── settings/           # base.py · local.py  (DJANGO_SETTINGS_MODULE=config.settings.local)
│   │   ├── urls.py             # root routes: /api/, /internal/, /recordings/<file>
│   │   ├── celery.py           # Celery app, Redis broker/backend, beat schedule
│   │   └── recordings.py       # serve_recording() → /recordings/<run-id>.wav
│   │
│   ├── apps/
│   │   ├── tenants/            # PUBLIC schema: Tenant, Domain, TenantAPIKey
│   │   │   ├── models.py
│   │   │   └── permissions.py  # API-key auth (the view-layer half)
│   │   │
│   │   ├── agents/             # the agent under test + live calls
│   │   │   ├── models.py       # Agent, Call, Transcript, CallMetric
│   │   │   ├── chat.py         # AgentChat — Claude Haiku brain (TEXT mode + pipeline LLM)
│   │   │   ├── views.py        # public REST: /api/agents/, /api/calls/
│   │   │   ├── internal_views.py / internal_urls.py   # /internal/calls/* (pipecat → django)
│   │   │   └── serializers.py
│   │   │
│   │   ├── testing/            # ★ the core of the product
│   │   │   ├── models.py       # Scenario, TestRun, TestResult, JudgeScore
│   │   │   ├── runner.py       # run_scenario() — orchestrates a run; _check_assertion()
│   │   │   ├── caller.py       # CallerInterface: TextCaller / AudioCaller; strip_quirks()
│   │   │   ├── quirks.py       # Voice Quirks DSL parsing helpers
│   │   │   ├── judge.py        # evaluate_result() — Claude Sonnet rubric scoring (pass ≥ 0.7)
│   │   │   ├── tasks.py        # run_scenario_task · run_judge_task (Celery)
│   │   │   ├── views.py        # /api/test-runs/, /api/scenarios/
│   │   │   └── management/     # load_scenarios command (YAML → DB)
│   │   │
│   │   └── monitoring/         # metrics + alerting
│   │       ├── models.py       # AlertConfig, AlertEvent
│   │       ├── metrics.py      # rollup computations
│   │       └── tasks.py        # beat-scheduled alert/metric tasks
│   │
│   └── tests/                  # pytest suite (config.settings.local; API-key auth patched)
│       ├── conftest.py
│       └── test_*.py           # api_smoke, caller, judge, monitoring, cli
│
├── pipecat_agent/              # ── VOICE RUNTIME (Python 3.12 / linux-amd64) ───────
│   ├── server.py               # :8001 AGENT — /connect, /caller/run, /health
│   ├── pipeline.py             # run_voice_agent(): Scribe v2 STT → Haiku → 11Labs TTS;
│   │                           #   RetryingElevenLabsTTSService; _notify_django() → /internal
│   ├── caller_server.py        # :8002 CALLER — /run, /health
│   ├── caller_bot.py           # ScenarioCallerBot, Turn; mixes both sides → mono 16kHz WAV
│   ├── caller_bot_main.py      # standalone caller entry (main())
│   ├── config.py               # voice IDs, model names, defaults
│   ├── Dockerfile
│   └── requirements.txt
│
├── cli/                        # ── shunya CLI (Typer) ──────────────────────────────
│   ├── main.py                 # commands: agents / scenarios / tests / calls
│   └── client.py               # HTTP client (reads SHUNYA_API_KEY, SHUNYA_TENANT_HOST)
│
├── scenarios/                  # scenario YAML (load_scenarios syncs → DB)
│   └── *.yaml                  # angry_customer_refund, booking_happy_path, …
│
├── agents/                     # sample agent definitions (YAML system prompts)
│   └── *.yaml                  # banking_support_agent, hotel_concierge, …
│
├── recordings/                 # generated <run-id>.wav files (audio-mode output)
└── setup.py                    # installs the `shunya` console entry point
```

### Quick "where do I…?" index

| I want to…                                   | Go to                                                            |
|----------------------------------------------|-----------------------------------------------------------------|
| Change how a scenario is driven / orchestrated | `apps/testing/runner.py`                                       |
| Add/modify a Voice Quirks DSL tag            | `apps/testing/quirks.py` + `caller.py` (`strip_quirks`)         |
| Tune the rubric scoring or pass threshold    | `apps/testing/judge.py`                                          |
| Change the agent's brain (text mode)         | `apps/agents/chat.py` (`AgentChat`, Haiku)                       |
| Change the voice pipeline (STT/LLM/TTS)      | `pipecat_agent/pipeline.py`                                      |
| Change the synthetic caller's behavior       | `pipecat_agent/caller_bot.py` (`ScenarioCallerBot`)             |
| Talk to an agent live in a browser           | `shunya agents connect <id>` → `POST /api/agents/<id>/connect/` |
| Add a REST endpoint                          | the relevant `apps/<app>/views.py` + `urls.py`                  |
| Add a Celery task                            | `apps/<app>/tasks.py` (remember the `schema_name` arg!)         |
| Add a model / migrate                        | `apps/<app>/models.py` → `python manage.py migrate`             |
| Add a CLI command                            | `cli/main.py` (+ `cli/client.py` for new HTTP calls)            |
| Touch tenant routing / API keys              | `apps/tenants/` (`models.py`, `permissions.py`)                 |
| Serve / locate a call recording             | `config/recordings.py`; files in `recordings/`                  |

---

## 6. Domain Glossary

| Term                  | Meaning                                                                          |
|-----------------------|----------------------------------------------------------------------------------|
| **Agent under test**  | The conversational AI Shunya is QA-ing (text via `AgentChat`, voice via pipecat) |
| **Scenario**          | A persona + ordered `steps` + `assertions` + optional `rubric` (YAML → DB)        |
| **Voice Quirks DSL**  | Inline step annotations (`[stutter]`, `[pause:3s]`, `[hard_input:"…"]`, …)         |
| **TestRun**           | One execution of a scenario against an agent in a mode (`text`/`audio`)            |
| **TestResult**        | The transcript + outcome produced by a TestRun                                    |
| **JudgeScore**        | Per-rubric-field score (0.0–1.0) from the Claude Sonnet judge; pass ≥ 0.7          |
| **CallerInterface**   | Abstraction the runner uses; `TextCaller` (in-process) or `AudioCaller` (WebRTC)   |
| **ScenarioCallerBot** | The synthetic caller bot that joins the Daily room and speaks the scenario steps   |

---

## 7. Models (LLM usage)

| Use                         | Model                          | Where                       |
|-----------------------------|--------------------------------|-----------------------------|
| Agent brain (under test)    | `claude-haiku-4-5-20251001`    | `apps/agents/chat.py`, pipeline |
| LLM judge (rubric scoring)  | `claude-sonnet-4-6`            | `apps/testing/judge.py`     |
| STT (audio mode)            | ElevenLabs **Scribe v2**       | `pipecat_agent/pipeline.py`, `caller_bot.py` |
| TTS (audio mode)            | ElevenLabs                     | `pipecat_agent/pipeline.py`, `caller_bot.py` |

---

## 8. Gotchas Worth Repeating

- **Celery worker does not auto-reload.** After editing `runner.py`, `judge.py`, or any task:
  `docker-compose restart celery_worker`. (Django, pipecat, caller all run `--reload`.)
- **Always pass `schema_name` to tasks** — omitting it ⇒ `relation does not exist`.
- **Two voice processes are intentional** — one `CallClient` per process limit.
- **ElevenLabs TTS `output_format` is a query param**, not a body field (else MP3 → VAD noise).
- **Empty `voice_id` ⇒ opaque 403** — always `voice_id or DEFAULT`.
- See `TECH_SPEC.md` for the full audio-mode engineering notes (VAD ordering, thread affinity).
```