# Shunya — Low-Level Design Flow

> File references use short paths relative to `zenerate/web-py/`.

---

## 1. Authentication

Three parallel auth paths, all resolved by Django middleware before any view runs.

```mermaid
flowchart TD
    REQ([Incoming Request]) --> MW1

    subgraph Middleware Stack - apps/api/zenapi/config/settings/__init__.py
        MW1[MultitenantContextMiddleware\nresolves tenant from token / header]
        MW2[TenantAPIKeyMiddleware\nvalidates Api-Key header]
        MW3[MultitenantRLSMiddleware\nSET LOCAL app.current_tenant_id]
        MW1 --> MW2 --> MW3
    end

    MW1 -- Knox token --> KA[KnoxTokenAuthentication\nUI login flow]
    MW2 -- Api-Key header --> AK[TenantAPIKey.authenticate\npackages/agent/.../models/__init__.py\n\nBypasses RLS via cross_tenant_access\nflag to find key before tenant is known]
    MW2 -- X-Service-Token --> ST[ServiceTokenAuthentication\ncaller service → internal endpoints]

    AK --> RLS
    KA --> RLS
    ST --> RLS
    RLS[Postgres RLS active\napp.current_tenant_id = tenant.id\nall ORM queries auto-scoped]
```

---

## 2. ElevenLabs Integration

```mermaid
flowchart TD
    UI([Web UI / CLI]) -->|GET /api/v1/integrations/elevenlabs/| GV[Return configured + key_hint\nElevenLabsIntegrationView\npackages/agent/.../views/__init__.py]

    UI -->|PUT with api_key| PV[Validate key against\nElevenLabs /convai/agents\nvia httpx]
    PV -- 401 --> ERR[Return 400 bad key]
    PV -- 200 --> SAVE[ElevenLabsCredential.objects.update_or_create\npackages/agent/.../models/__init__.py]

    UI -->|DELETE /api/v1/integrations/elevenlabs/| DEL[ElevenLabsCredential.objects.delete\n204 No Content]
```

---

## 3. Agent Listing & ElevenLabs Sync

```mermaid
flowchart TD
    UI -->|GET /api/v1/agents/| LIST[AgentViewSet.list\nfilter target_type=ELEVENLABS\npackages/agent/.../views/__init__.py]
    LIST --> DB1[(Agent table\nlocal cache of EL agents)]

    UI -->|POST /api/v1/agents/sync-elevenlabs/| SYNC[AgentViewSet.sync_elevenlabs]
    SYNC --> CRED[Load ElevenLabsCredential\nfor tenant]
    CRED -- not found --> E400[400 — connect EL first]
    CRED -- found --> EL[GET api.elevenlabs.io/v1/convai/agents\nwith tenant's xi-api-key]
    EL --> UPS[Agent.objects.update_or_create\nper remote agent]
    UPS --> DEACT[Mark disappeared agents INACTIVE]
    DEACT --> RET[Return fresh agent list]
```

---

## 4. Scenario CRUD

```mermaid
flowchart TD
    UI -->|GET /api/v1/scenarios/| SL["ScenarioViewSet.list · filter ten.../views/__init__.py"]
                                                                                                                                                                          UI -->|POST /api/v1/scenarios/| SC[ScenarioViewSet.create]
    SC --> SER["ScenarioSerializer.validate · packages/agent/.../serializers/__init__.py · auto-generates yaml_content if omitted · normalises steps via parse_step · packages/agent/.../services/quirks.py"]
    SER --> DB2[("Scenario table · steps as JSONB · text · raw · quirks")]

    UI -->|PATCH /api/v1/scenarios/id/| UP["ScorioViewSet.update · partial update"]
    UI -->|DELETE /api/v1/scenarios/id/| DEL2[ScenarioViewSet.destroy]

    CLI -->|manage.py load_scenarios| YAML["Parse YAML files in scenarioement/commands/load_scenarios.py · bulk upsert into Scenario table"]
```

---

## 5. Test Run Creation

### 5a. Single Run

```mermaid
flowchart TD
    UI -->|POST /api/v1/test-runs/\nbody: agent, scenario, mode| TV[TestRunViewSet.create\npackages/agent/.../views/__init__.py]
    TV --> LOOK[Lookup Agent + Scenario\nby UUID or name]
    LOOK --> TR[TestRun.objects.create\nstatus: queued]
    TR -->|.delay| CEL[run_scenario_task pushed to Redis\npackages/agent/.../tasks.py]
    CEL --> RET2[Return TestRun JSON\nHTTP 201 — request done]
    CEL -.->|async| WORK[Celery worker picks up task]
```

### 5b. Bulk Run — run-evals

```mermaid
flowchart TD
    UI -->|POST /api/v1/agents/id/run-evals/| RE[AgentViewSet.run_evals\npackages/agent/.../views/__init__.py]
    RE --> QS[Query compatible scenarios\nM2M or universal]
    QS --> CRT[Create one TestRun per scenario]
    CRT --> GRP[celery_group of run_scenario_task calls\ndispatched in parallel]
    GRP --> IDS[Persist celery task IDs for observability]
    IDS --> RET3[Return all TestRun rows + group_id\nHTTP 201]
```

---

## 6. Text Mode Call Flow (BUILTIN agents) — Synchronous inside Celery

```mermaid
flowchart TD
    WORK[Celery Worker\nrun_scenario_task\npackages/agent/.../tasks.py] --> RS[runner.run_scenario\npackages/agent/.../services/runner.py]

    RS --> SET[Set RLS context\ncontext.current_tenant.set]
    SET --> TC[TextCaller\npackages/agent/.../services/caller.py]

    TC -->|per step| STRIP[strip_quirks — remove DSL tags\npackages/agent/.../services/quirks.py]
    STRIP --> AC[AgentChat.send\npackages/agent/.../services/chat.py\n\nPOST anthropic messages.create\nmodel: claude-haiku-4-5]
    AC --> TURN[Append turn to transcript]
    TURN -->|next step| TC

    TURN --> DONE[All steps complete]
    DONE --> ASSERT[_evaluate_assertions\nheuristic checks\nresolved_within_5_turns etc]
    ASSERT --> TRES[TestResult.objects.create\npassed + transcript]
    TRES --> PROMOTE[_promote_live_scores\nno live scores in text mode → False]
    PROMOTE --> JUDGE[_post_call_score\npackages/agent/.../services/runner.py]
    JUDGE --> JSCORE[score_transcript\npackages/agent/.../services/judge.py\n\nPOST claude-sonnet-4-6\nreturns JSON scores per rubric field]
    JSCORE --> BULK[JudgeScore.objects.bulk_create\none row per rubric field]
    BULK --> DONE2[TestRun.status = completed]
```

---

## 7. Remote Mode Call Flow (ELEVENLABS agents) — Mixed sync + async

```mermaid
sequenceDiagram
    participant CW as Celery Worker<br/>tasks.py
    participant RN as runner.py
    participant RC as RemoteAudioCaller<br/>services/caller.py
    participant CS as Caller Service :8002<br/>services/voice/caller_server.py
    participant EA as EvalAgent<br/>services/voice/eval_agent.py
    participant EL as ElevenLabs<br/>ConvAI WebSocket
    participant SC as Scorer<br/>services/voice/eval_agent.py
    participant DJ as Django Internal API<br/>urls/internal.py

    CW->>RN: run_scenario(run_id)
    RN->>CS: POST /remote/connect<br/>→ Daily room created, observer_url saved
    RN->>CS: POST /remote/run<br/>el_agent_id + steps + recording_id
    CS->>EA: EvalAgent.run(steps)
    EA->>EL: WebSocket connect
    loop per scenario step
        EA->>EL: send caller utterance
        EL-->>EA: agent audio + transcript
        EA->>SC: Scorer.score(turn, transcript_so_far)
        SC->>SC: concurrent Claude Sonnet calls<br/>one per rubric field
        SC->>DJ: POST /internal/test-runs/id/live-scores/<br/>atomic batch — merge by field<br/>LiveScoresView in urls/internal.py
        DJ-->>SC: 200
    end
    EA-->>CS: transcript[]
    CS-->>RC: transcript[]
    RC-->>RN: transcript[]
    RN->>RN: TestResult.objects.create
    RN->>RN: _promote_live_scores()<br/>reads final live_scores JSON<br/>bulk_create → JudgeScore rows
    Note over RN: _post_call_score skipped<br/>live scores already exist
    RN->>CW: TestRun.status = completed
```

---

## 8. Internal Endpoints (Caller → Django only)

```mermaid
flowchart TD
    CS[Caller Service :8002] -->|X-Service-Token + X-Tenant-Id| INT

    subgraph INT[Internal API — packages/agent/.../urls/internal.py]
        I1[POST /internal/calls/start/\ncreate Call row]
        I2[POST /internal/calls/id/turn/\nappend turn to Transcript]
        I3[POST /internal/calls/id/end/\nclose Call, dispatch compute_call_metrics]
        I4[POST /internal/test-runs/id/live-scores/\nLiveScoresView — merge scores by field\nsaved to TestRun.live_scores JSONB]
    end

    I3 --> CM[compute_call_metrics Celery task\npackages/agent/.../tasks.py]
```

---

## 9. 3-Tier Verdict System

```mermaid
flowchart LR
    CALL[Call ends] --> T1

    subgraph T1[Tier 1 — Heuristic]
        H[_evaluate_assertions\nrunner.py\nno LLM — counts turns,\nchecks known assertion names]
    end

    subgraph T2[Tier 2 — Live Scores\nRemote mode only]
        L[Scorer in EvalAgent\neval_agent.py\nClaude Sonnet after each turn\n→ live_scores JSONB on TestRun\n→ promoted to JudgeScore by\n_promote_live_scores]
    end

    subgraph T3[Tier 3 — Post-call Judge\nText mode only, skipped if T2 ran]
        J[score_transcript\njudge.py\nClaude Sonnet on full transcript\n→ JudgeScore bulk_create]
    end

    T1 --> T2
    T2 --> T3
    T3 --> VR[Verdict\nTestResultSerializer.get_verdict\nserializers/__init__.py\nsuccess / partial / failed]
```

---

## 10. Web UI Data Flow

```mermaid
flowchart TD
    B[Browser] -->|localStorage: shunya_api_key| AG[ApiKeyGate\ncomponents/api-key-gate.tsx]
    AG -->|no key| GATE1[Full-screen key entry]
    AG -->|key present| EG[ElevenLabsGate\ncomponents/elevenlabs-gate.tsx]
    EG -->|GET /api/v1/integrations/elevenlabs/\nnot configured| GATE2[Full-screen EL key entry]
    EG -->|configured| APP[App renders\napp/layout.tsx]

    APP --> SB[Sidebar\ncomponents/layout/sidebar.tsx\nSWR polls /integrations/elevenlabs/\nConnect / Disconnect button]

    APP --> PAGES

    subgraph PAGES[Pages - app]
        P1[agents - AgentViewSet list]
        P2[scenarios - ScenarioViewSet list]
        P3[tests - TestRunViewSet list\nSWR refreshInterval=3s while running]
        P4[tests/id - single run\nSWR refreshInterval=2s while queued/running\nTranscript + ScoreBar + audio player]
    end

    P4 -->|run completed| SCORES[JudgeScore rows\nrendered via TestResultSerializer\nscores nested in result field]
```

---

## File Map Quick Reference

| Area | Key File |
|---|---|
| RLS multi-tenancy | `packages/mt/src/zenlib/reusable_apps/multitenant/models.py` |
| Auth middleware | `apps/api/zenapi/config/settings/__init__.py` |
| All tenant models | `packages/agent/.../voice_qa/models/__init__.py` |
| All public views | `packages/agent/.../voice_qa/views/__init__.py` |
| Internal endpoints | `packages/agent/.../voice_qa/urls/internal.py` |
| Serializers | `packages/agent/.../voice_qa/serializers/__init__.py` |
| Celery tasks | `packages/agent/.../voice_qa/tasks.py` |
| Scenario runner | `packages/agent/.../voice_qa/services/runner.py` |
| Text caller + AgentChat | `packages/agent/.../voice_qa/services/caller.py` + `chat.py` |
| Voice Quirks DSL | `packages/agent/.../voice_qa/services/quirks.py` |
| Post-call judge | `packages/agent/.../voice_qa/services/judge.py` |
| Caller HTTP server | `services/voice/caller_server.py` |
| EvalAgent + Scorer | `services/voice/eval_agent.py` |
| Next.js entry | `services/web/app/layout.tsx` |
| API fetch wrapper | `services/web/lib/api.ts` |
| TS types | `services/web/lib/types.ts` |
