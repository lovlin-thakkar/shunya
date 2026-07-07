# Shunya — Low-Level Design Flow

> Paths are relative to `zenerate/web-py/`.
> Sync steps are marked [S], async/background steps are marked [A].

───────────────────────────────────────────────────────────────────────────────

## 1. Authentication

Three parallel paths — all resolved before any view runs.

                    ┌─────────────────────────────────────────┐
                    │           Incoming Request               │
                    └──────────────────┬──────────────────────┘
                                       │
                    ┌──────────────────▼──────────────────────┐
                    │      MultitenantContextMiddleware    [S] │
                    │  resolves tenant from Knox token or      │
                    │  X-Tenant-Id header                      │
                    │  apps/api/zenapi/config/settings/        │
                    └──────┬──────────────┬────────────────────┘
                           │              │
              ┌────────────▼───┐    ┌─────▼──────────────────────────┐
              │  Knox Token    │    │   TenantAPIKeyMiddleware    [S] │
              │  (UI login)    │    │   reads Authorization: Api-Key  │
              └────────┬───────┘    └─────────────┬──────────────────┘
                       │                          │
                       │              ┌───────────▼────────────────────────────┐
                       │              │  TenantAPIKey.authenticate()       [S] │
                       │              │  packages/agent/.../models/__init__.py  │
                       │              │                                         │
                       │              │  Problem: RLS blocks key lookup because  │
                       │              │  tenant not known yet (chicken & egg)    │
                       │              │                                         │
                       │              │  Fix: set_config(cross_tenant_access,   │
                       │              │  true) → find key → reset immediately   │
                       │              └───────────┬────────────────────────────┘
                       │                          │
              ┌────────▼──────────────────────────▼────────────────┐
              │           MultitenantRLSMiddleware              [S] │
              │   SET LOCAL app.current_tenant_id = <tenant.id>     │
              │   All ORM queries now auto-scoped by Postgres RLS   │
              │   apps/api/zenapi/config/settings/                  │
              └─────────────────────┬──────────────────────────────┘
                                    │
                              Views / Tasks

      ┌─────────────────────────────────────────────────────────────┐
      │  Caller Service uses a separate path:                       │
      │  X-Service-Token + X-Tenant-Id → ServiceTokenAuthentication │
      │  only accepted on /internal/* endpoints                     │
      │  packages/agent/.../urls/internal.py                        │
      └─────────────────────────────────────────────────────────────┘

───────────────────────────────────────────────────────────────────────────────

## 2. ElevenLabs Integration

     ┌──────────────────────────────────────────────────────────────┐
     │                    ElevenLabsIntegrationView             [S] │
     │                packages/agent/.../views/__init__.py          │
     └──────────────┬──────────────────┬──────────────┬────────────┘
                    │                  │              │
           ┌────────▼───────┐ ┌────────▼─────────┐ ┌▼────────────────┐
           │ GET             │ │ PUT              │ │ DELETE          │
           │ return          │ │ validate api_key │ │ ElevenLabsCred  │
           │ configured:bool │ │ against EL API   │ │ .objects.delete │
           │ key_hint:str    │ │ via httpx        │ │ 204 response    │
           └────────────────┘ └────────┬─────────┘ └─────────────────┘
                                       │
                          ┌────────────▼────────────────┐
                          │  401 from ElevenLabs?        │
                          │  → return 400 bad key        │
                          │  200?                        │
                          │  → ElevenLabsCredential      │
                          │    .update_or_create         │
                          │    packages/agent/...        │
                          │    /models/__init__.py       │
                          └─────────────────────────────┘

      ElevenLabsGate (web UI) calls GET on mount.           [S]
      If not configured → full-screen key entry screen.
      components/elevenlabs-gate.tsx

───────────────────────────────────────────────────────────────────────────────

## 3. Agent Listing & ElevenLabs Sync

     GET /api/v1/agents/
     ──────────────────
     AgentViewSet.list                                       [S]
     packages/agent/.../views/__init__.py
         │
         └──→ Agent.objects.filter(
                  tenant=current_tenant,
                  target_type=ELEVENLABS,
                  status=ACTIVE
              )
              └──→ return AgentSerializer list
                   packages/agent/.../serializers/__init__.py


     POST /api/v1/agents/sync-elevenlabs/
     ─────────────────────────────────────
     AgentViewSet.sync_elevenlabs                            [S]
     packages/agent/.../views/__init__.py
         │
         ├──→ load ElevenLabsCredential for tenant
         │       └── none found → 400 "connect EL first"
         │
         ├──→ GET api.elevenlabs.io/v1/convai/agents
         │       with tenant's xi-api-key  (httpx, timeout=20s)
         │       └── 401 → 400 "bad key / needs convai_read"
         │
         ├──→ for each remote agent:
         │       Agent.objects.update_or_create(
         │           el_agent_id=..., target_type=ELEVENLABS
         │       )
         │
         └──→ Agent.objects.exclude(el_agent_id__in=seen)
                  .update(status=INACTIVE)
             └──→ return fresh agent list

───────────────────────────────────────────────────────────────────────────────

## 4. Scenario CRUD

     ┌──────────────────────────────────────────────────────────────┐
     │                     ScenarioViewSet                      [S] │
     │               packages/agent/.../views/__init__.py           │
     └───────┬──────────────┬───────────────┬──────────────┬───────┘
             │              │               │              │
         GET list       POST create     PATCH update   DELETE
             │              │               │
             │    ┌──────────▼────────────────────────────────────┐
             │    │  ScenarioSerializer.validate               [S] │
             │    │  packages/agent/.../serializers/__init__.py    │
             │    │                                                 │
             │    │  • auto-generate yaml_content if omitted       │
             │    │  • validate_steps: str → parse_step()          │
             │    │    packages/agent/.../services/quirks.py       │
             │    │    each step → {text, raw, quirks:[{tag,val}]} │
             │    └───────────────────────┬─────────────────────── ┘
             │                            │
             │              ┌─────────────▼──────────────────────┐
             │              │  Scenario table (JSONB steps)   [S] │
             │              │  packages/agent/.../models/         │
             └──────────────┘  __init__.py                        │
                               └────────────────────────────────── ┘

     CLI path:
     manage.py load_scenarios --dir ../../scenarios/            [S]
     packages/agent/.../management/commands/load_scenarios.py
         └──→ parse YAML files → Scenario.objects.update_or_create
              quirk tags parsed into steps JSONB

───────────────────────────────────────────────────────────────────────────────

## 5. Single Test Run Creation

     POST /api/v1/test-runs/
     ────────────────────────
     TestRunViewSet.create                                      [S]
     packages/agent/.../views/__init__.py
         │
         ├──→ lookup Agent by UUID                 (RLS-scoped)
         ├──→ lookup Scenario by UUID or name
         │       _uuid.UUID(str(scenario_name))
         │       → ValueError → lookup by name
         │
         ├──→ TestRun.objects.create(status=queued)
         │
         ├──→ run_scenario_task.delay(run.id, tenant.id)    [A]
         │       pushes message to Redis broker
         │       returns AsyncResult with task_id
         │
         ├──→ run.celery_task_id = task.id
         │
         └──→ return TestRunSerializer(run)   HTTP 201
              (request ends here — run executes in background)

───────────────────────────────────────────────────────────────────────────────

## 6. Bulk Test Runs — run-evals

     POST /api/v1/agents/{id}/run-evals/
     ─────────────────────────────────────
     AgentViewSet.run_evals                                     [S]
     packages/agent/.../views/__init__.py
         │
         ├──→ query compatible scenarios
         │       Scenario where compatible_agents includes this agent
         │       OR where compatible_agents is empty (universal)
         │
         ├──→ create one TestRun per scenario   (bulk)
         │
         ├──→ celery_group([
         │       run_scenario_task.s(run.id, tenant.id)
         │       for each run
         │    ]).apply_async()                               [A]
         │    all tasks dispatched in parallel to Redis
         │
         ├──→ persist individual task IDs to each TestRun
         │
         └──→ return {group_id, runs[], parallelism}   HTTP 201

───────────────────────────────────────────────────────────────────────────────

## 7. Text Mode Call — BUILTIN agents (fully synchronous inside worker)

     [A] Celery worker picks up run_scenario_task
     packages/agent/.../tasks.py
         │
         ├── context.current_tenant.set(tenant)   ← sets RLS for worker
         │
         └──→ runner.run_scenario(run_id)
              packages/agent/.../services/runner.py
                  │
                  ├── TestRun.status = running
                  ├── caller = TextCaller(agent)
                  │   packages/agent/.../services/caller.py
                  │
                  ├── [if agent.greeting]
                  │       append greeting turn to transcript
                  │
                  ├── for each step in scenario.steps:         [S loop]
                  │   │
                  │   ├──→ TextCaller.send(step.raw)
                  │   │       strip_quirks() → clean text
                  │   │       packages/agent/.../services/quirks.py
                  │   │
                  │   ├──→ AgentChat.send(clean_text)
                  │   │       packages/agent/.../services/chat.py
                  │   │       POST anthropic messages.create
                  │   │       model: claude-haiku-4-5-20251001
                  │   │       stateful per conversation_id
                  │   │
                  │   └── append {speaker, text, ts_ms, quirks} to transcript
                  │
                  ├──→ _evaluate_assertions(transcript, scenario.assertions)
                  │       heuristic checks (turn count, keyword match)
                  │       no LLM — synchronous
                  │
                  ├──→ TestResult.objects.create(
                  │       transcript=transcript,
                  │       assertion_results=[...]
                  │   )
                  │
                  ├──→ _promote_live_scores(run, result)
                  │       no live scores in text mode → returns False
                  │
                  └──→ _post_call_score(run, result, had_live=False)
                           packages/agent/.../services/runner.py
                               │
                               └──→ score_transcript(transcript, rubric)
                                    packages/agent/.../services/judge.py
                                        │
                                        ├── POST anthropic messages.create
                                        │   model: claude-sonnet-4-6
                                        │   timeout=30s, max_retries=1
                                        │   prompt: rubric fields + transcript
                                        │   returns JSON: {field: {score, reasoning, passed}}
                                        │
                                        └──→ JudgeScore.objects.bulk_create
                                             one row per rubric field
                                             packages/agent/.../models/__init__.py

───────────────────────────────────────────────────────────────────────────────

## 8. Remote Mode Call — ELEVENLABS agents (sync + async scoring)

     [A] Celery worker picks up run_scenario_task
     packages/agent/.../tasks.py
         │
         └──→ runner.run_scenario(run_id)
              packages/agent/.../services/runner.py
                  │
                  ├── caller = RemoteAudioCaller(agent)
                  │   packages/agent/.../services/caller.py
                  │
                  ├──→ POST caller:8002/remote/connect          [S]
                  │   services/voice/caller_server.py
                  │       └── provisions Daily.co room
                  │           saves observer_url to TestRun
                  │
                  ├──→ POST caller:8002/remote/run              [S blocks until call done]
                  │   services/voice/caller_server.py
                  │       │
                  │       └──→ EvalAgent.run(steps)
                  │            services/voice/eval_agent.py
                  │                │
                  │                ├── connect to ElevenLabs ConvAI WebSocket
                  │                │   (el_agent_id, xi-api-key)
                  │                │
                  │                ├── EvalBridge: Daily.co CallClient for live listen-in
                  │                │   only ONE active per process (_daily_bridge_in_use flag)
                  │                │   second concurrent run → WS only, no Daily relay
                  │                │
                  │                ├── for each step:
                  │                │   │
                  │                │   ├── send caller utterance over WS
                  │                │   ├── receive agent audio chunks
                  │                │   │     WAV write cursor: anchored to wall-clock
                  │                │   │     on first chunk, advances by len(pcm)/bytes_per_sec
                  │                │   │     (prevents burst-arrival collapse in recording)
                  │                │   │
                  │                │   ├──→ Scorer.score(turn_n, transcript_so_far)
                  │                │   │   services/voice/eval_agent.py
                  │                │   │       │
                  │                │   │       ├── concurrent Claude Sonnet calls
                  │                │   │       │   one per rubric field
                  │                │   │       │   model: claude-sonnet-4-6
                  │                │   │       │
                  │                │   │       └──→ POST /internal/test-runs/{id}/live-scores/
                  │                │   │            ONE atomic batch per turn
                  │                │   │                │
                  │                │   │                └── LiveScoresView           [S]
                  │                │   │                    packages/agent/...
                  │                │   │                    /urls/internal.py
                  │                │   │                    merge by field key:
                  │                │   │                    existing[field] = incoming[field]
                  │                │   │                    save to TestRun.live_scores JSONB
                  │                │   │
                  │                │   └── silence keepalive during scoring gap + TTS only
                  │                │       NOT during agent response (avoids WS overlap)
                  │                │
                  │                └── return transcript[]
                  │
                  ├── TestResult.objects.create
                  │
                  ├──→ _promote_live_scores(run, result)        [S]
                  │   packages/agent/.../services/runner.py
                  │       │
                  │       ├── refresh live_scores from DB (final turn batch)
                  │       ├── JudgeScore.objects.bulk_create(ignore_conflicts=True)
                  │       └── returns True
                  │
                  └── _post_call_score skipped (had_live=True)
                      TestRun.status = completed

───────────────────────────────────────────────────────────────────────────────

## 9. 3-Tier Verdict System

                    ┌──────────────────┐
                    │   Call Ends      │
                    └────────┬─────────┘
                             │
              ┌──────────────▼──────────────────────────────────────────┐
              │  TIER 1 — Heuristic Assertions                      [S] │
              │  runner._evaluate_assertions()                          │
              │  packages/agent/.../services/runner.py                  │
              │                                                          │
              │  • resolved_within_5_turns  → count transcript turns    │
              │  • known names → synchronous rule check                 │
              │  • unknown names → pass heuristically, flag for judge   │
              └──────────────────────────────────┬───────────────────── ┘
                                                 │
              ┌──────────────────────────────────▼───────────────────── ┐
              │  TIER 2 — Live Scores (remote mode only)            [A] │
              │  Scorer in services/voice/eval_agent.py                 │
              │                                                          │
              │  • runs after EACH agent turn (concurrent Sonnet calls) │
              │  • one atomic POST per turn to /internal/live-scores/   │
              │  • stored in TestRun.live_scores JSONB (merge by field) │
              │  • after call: _promote_live_scores() → JudgeScore rows │
              │                                                          │
              │  Skipped entirely in text mode                          │
              └──────────────────────────────────┬───────────────────── ┘
                                                 │
              ┌──────────────────────────────────▼───────────────────── ┐
              │  TIER 3 — Post-call Judge (text mode only)          [S] │
              │  runner._post_call_score()                              │
              │  packages/agent/.../services/runner.py                  │
              │                                                          │
              │  Skipped if Tier 2 ran (_promote returned True)         │
              │                                                          │
              │  • score_transcript(full_transcript, rubric)            │
              │    packages/agent/.../services/judge.py                 │
              │  • Claude Sonnet, timeout=30s, single call              │
              │  • JudgeScore.objects.bulk_create (one per field)       │
              └──────────────────────────────────┬───────────────────── ┘
                                                 │
              ┌──────────────────────────────────▼───────────────────── ┐
              │  Verdict computed at read-time (not stored)             │
              │  TestResultSerializer.get_verdict()                     │
              │  packages/agent/.../serializers/__init__.py             │
              │                                                          │
              │  weighted_avg ≥ 0.7 + passed=True  →  "success"        │
              │  weighted_avg ≥ 0.7 + passed=False →  "partial"        │
              │  weighted_avg < 0.7                →  "failed"          │
              └────────────────────────────────────────────────────────┘

───────────────────────────────────────────────────────────────────────────────

## 10. Internal Endpoints (Caller Service → Django only)

     All routes under /internal/ — no tenant auth, service token only.
     packages/agent/.../urls/internal.py

     ┌──────────────────────────────────────────────────────────────────┐
     │  Caller Service :8002                                            │
     │  services/voice/caller_server.py                                 │
     └──────────┬────────────────────────────────────────────┬─────────┘
                │ X-Service-Token + X-Tenant-Id              │
                │                                            │
       ┌────────▼────────────────┐              ┌────────────▼──────────────────┐
       │ POST /internal/         │              │ POST /internal/test-runs/     │
       │   calls/start/          │              │   {id}/live-scores/           │
       │   calls/{id}/turn/      │              │                               │
       │   calls/{id}/end/       │              │ LiveScoresView                │
       │                         │              │ merge scores by field key     │
       │ create/update Call +    │              │ into TestRun.live_scores JSONB│
       │ Transcript rows         │              └───────────────────────────────┘
       └────────────┬────────────┘
                    │
          calls/{id}/end/ dispatches:
          compute_call_metrics.delay(call_id, tenant_id)    [A]
          packages/agent/.../tasks.py

───────────────────────────────────────────────────────────────────────────────

## 11. Web UI Data Flow

     Browser
         │
         ├──→ ApiKeyGate                                              [S]
         │    components/api-key-gate.tsx
         │    reads localStorage["shunya_api_key"]
         │        │
         │        ├── no key → full-screen key entry modal
         │        └── key present ──→ ElevenLabsGate
         │                           components/elevenlabs-gate.tsx
         │                               │
         │                               ├── GET /api/v1/integrations/elevenlabs/
         │                               ├── not configured → full-screen EL key entry
         │                               └── configured ──→ App renders
         │
         └──→ App Layout
              app/layout.tsx
                  │
                  ├── Sidebar (always mounted)
                  │   components/layout/sidebar.tsx
                  │   SWR polls /api/v1/integrations/elevenlabs/
                  │   shows Connect / Disconnect ElevenLabs button
                  │   ConnectElevenLabsModal on click
                  │   components/connect-elevenlabs-modal.tsx
                  │
                  └── Pages
                      │
                      ├── /agents          → GET /api/v1/agents/
                      │                     AgentViewSet.list
                      │
                      ├── /scenarios       → GET /api/v1/scenarios/
                      │                     ScenarioViewSet.list
                      │
                      ├── /tests           → GET /api/v1/test-runs/
                      │   app/tests/         SWR refreshInterval=3s
                      │   page.tsx           while any run is queued/running
                      │
                      └── /tests/{id}      → GET /api/v1/test-runs/{id}/
                          app/tests/[id]/    SWR refreshInterval=2s
                          page.tsx           while queued or running, stops on complete
                              │
                              ├── StatusBadge     components/status-badge.tsx
                              ├── Transcript      components/transcript.tsx
                              ├── ScoreBar ×N     components/score-bar.tsx
                              │   (from result.scores via TestResultSerializer)
                              └── audio player
                                  fetchRecordingBlobUrl(run.id)
                                  lib/api.ts
                                  GET /api/v1/test-runs/{id}/recording/
                                  (authenticated, streams WAV with Api-Key header)

───────────────────────────────────────────────────────────────────────────────

## File Map

     Auth & tenancy
       packages/mt/src/zenlib/reusable_apps/multitenant/models.py     Tenant, RLS policies
       apps/api/zenapi/config/settings/__init__.py                     middleware stack, CORS

     Models
       packages/agent/.../voice_qa/models/__init__.py                  all models + TenantAPIKey

     API layer
       packages/agent/.../voice_qa/views/__init__.py                   all public ViewSets + ElevenLabsIntegrationView
       packages/agent/.../voice_qa/urls/internal.py                    internal endpoints + LiveScoresView
       packages/agent/.../voice_qa/serializers/__init__.py             all serializers incl. verdict logic

     Business logic
       packages/agent/.../voice_qa/tasks.py                            Celery task definitions
       packages/agent/.../voice_qa/services/runner.py                  run_scenario, _promote_live_scores, _post_call_score
       packages/agent/.../voice_qa/services/caller.py                  TextCaller, RemoteAudioCaller, get_caller
       packages/agent/.../voice_qa/services/chat.py                    AgentChat (Claude Haiku, stateful)
       packages/agent/.../voice_qa/services/judge.py                   score_transcript (Claude Sonnet)
       packages/agent/.../voice_qa/services/quirks.py                  parse_step, strip_quirks, Voice Quirks DSL

     Caller service
       services/voice/caller_server.py                                 FastAPI server, /remote/connect, /remote/run
       services/voice/eval_agent.py                                    EvalAgent (WS), EvalBridge (Daily), Scorer

     Web UI
       services/web/app/layout.tsx                                     root layout, gates
       services/web/app/tests/[id]/page.tsx                            run detail, live polling
       services/web/components/elevenlabs-gate.tsx                     full-screen EL key gate
       services/web/components/connect-elevenlabs-modal.tsx            sidebar modal
       services/web/components/layout/sidebar.tsx                      nav + connect/disconnect button
       services/web/lib/api.ts                                         apiFetch wrapper, blob URL helper
       services/web/lib/types.ts                                       TypeScript types
