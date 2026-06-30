# PRD — Shunya (In-House Cekura)

**Status:** Built (MVP complete — text + audio modes, judge, monitoring, CLI, call recording)
**Stack decisions:** See PLAN.md (note the [Amendments During Build](PLAN.md#amendments-during-build) — STT, agent LLM, deployment, and audio-mode scope all changed)

---

## Problem

Teams building voice AI agents have no fast, automated way to test agent behavior before deployment, or to know when quality degrades in production. Manual QA doesn't scale; generic test tools don't understand voice-specific failure modes.

---

## What We're Building

A two-part platform:
1. **Voice Agent** — a real Pipecat-powered voice agent (Daily WebRTC + **ElevenLabs Scribe v2** STT + **Claude Haiku 4.5** + ElevenLabs TTS). Humans can call it via browser; it is also the system under test for audio fidelity mode.
2. **QA Platform** — automated testing in two modes, monitoring, evaluation, and **call recording**. Multi-tenant, API-first, CLI-driven.

> **Stack note:** Original scoping (PLAN.md) chose Deepgram STT + GPT-4o. During build these became **ElevenLabs Scribe v2** (one voice vendor) and **Claude Haiku 4.5** (one AI stack for agent + judge). The whole system runs **Docker-first** because the Daily SDK doesn't support Python 3.14.

---

## Users

| Persona | Need |
|---|---|
| **Agent Developer** | Run automated test scenarios before shipping; catch regressions early |
| **QA Engineer** | Author scenarios, review LLM judge scores, configure alert thresholds |
| **Ops / On-call** | Receive webhook alerts when a live call breaches quality thresholds |

---

## Features

### F1 — Voice Agent
- Pipecat pipeline (Pipecat 1.4): Daily.co (WebRTC) → **ElevenLabs Scribe v2** (STT) → **Claude Haiku 4.5** (LLM) → ElevenLabs (TTS)
- VAD is wired via a standalone `VADProcessor` (Silero) **before** the segmented STT — in Pipecat 1.4 `DailyParams` no longer takes `vad_analyzer`
- Deployed as a FastAPI service; agent config (system prompt, voice ID) pulled from Django at call start via `POST /connect`
- Agent registered in Django DB per tenant; ephemeral Daily.co room created per call
- Also exposes `POST /api/agents/{id}/chat/` — direct text endpoint used by TextCaller (bypasses STT/TTS), running Claude Haiku in-process inside Django

**Acceptance criteria:**
- A browser client can connect via Daily.co and have a real-time voice conversation with the agent
- Agent config (prompt, voice) updatable via API without restarting Pipecat server
- Each call produces a transcript and CallMetric stored in DB
- `shunya agents create --name "..." --prompt "..."` registers an agent

---

### F2 — Scenario Runner (QA Engine)
- Scenarios defined in YAML: persona, conversation steps, success assertions
- **Two test modes**, selectable per run (`--mode text|audio`):

**Text mode (default — fast, parallel):**
- TextCaller injects text directly into the agent's Claude Haiku brain via `/api/agents/{id}/chat/`
- Voice Quirks DSL annotates simulated conditions inline:
  - Speech behavior: `[pause:3s]`, `[stutter]`, `[slow_speech]`
  - Conversation dynamics: `[interrupt]`, `[background_noise]`
  - Special case inputs: `[hard_input:"Praneeth Krishnamurthy"]`, `[email:"x@domain.com"]`, `[phone:"415-555-0192"]`
- Bypasses STT/TTS; 10 scenarios in parallel under 60s

**Audio fidelity mode (realistic — tests full stack) — ✅ shipped:**
- The synthetic caller (`ScenarioCallerBot`) runs as a **separate FastAPI service** (`caller_server.py` on :8002) — `daily-python` can't host two `CallClient`s in one process, so the caller is isolated from the agent pipeline
- It synthesizes each step with ElevenLabs TTS and injects it into the Daily room via a **virtual microphone**; it captures the agent's audio via a **virtual speaker** and transcribes with Scribe v2
- Audio goes through the full pipeline: ElevenLabs Scribe → Claude Haiku → ElevenLabs TTS → caller hears response
- A **readiness gate** holds the caller until the agent's TTS WebSocket is connected, so the first turn isn't lost
- Captures a real bidirectional voice conversation; sequential (one bot-to-bot conversation per run)
- Every audio run is **recorded** to a WAV (see F6)

**YAML schema (minimal):**
```yaml
name: angry_customer_refund
persona: "Frustrated customer demanding a refund. Short, impatient replies."
steps:
  - "[stutter] I w-want a refund for my order"
  - "[interrupt] No wait — I said refund, not exchange"
  - "My name is [hard_input:\"Praneeth Krishnamurthy\"], look up my account"
assertions:
  - agent_acknowledges_frustration
  - no_hallucinated_policy
  - resolved_within_5_turns
```

**Acceptance criteria:**
- `shunya test run <agent-id> --scenario <name> --mode text` triggers a text mode run
- `shunya test run <agent-id> --scenario <name> --mode audio` triggers an audio fidelity run
- Text mode: 10 scenarios in parallel, complete under 60s
- Audio mode: sequential, full call recorded and transcript stored
- Results queryable via `shunya test results <run-id>`

---

### F3 — LLM Judge
- Post-run, **Claude Sonnet 4.6** evaluates the full transcript against a rubric (single call)
- Default rubric fields (aligned with Cekura's evaluation dimensions), each scored **0.0–1.0**:

| Field | What it measures |
|---|---|
| `instruction_following` | Did the agent adhere to its configured policies? (e.g. return rules, escalation paths) |
| `goal_completion` | Did the call achieve its stated purpose? (booking made, issue resolved) |
| `interruption_handling` | Did the agent recover gracefully when the user cut it off? |
| `tool_call_accuracy` | Were any tool/API calls made with correct parameters? (N/A if no tools) |
| `csat_tone` | Was the interaction pleasant? Would the user likely be satisfied? |
| `safety` | No hallucinated policies, no harmful or incorrect information given |

- Each field is scored 0.0–1.0; **pass threshold is ≥ 0.7** per field. Weighted overall pass.
- Rubric is configurable per scenario — fields can be omitted or reweighted (weights in the scenario YAML's `rubric:` block)
- Each `JudgeScore` row stores the field, score, one-line reasoning, and passed flag

**Acceptance criteria:**
- Every completed test run has a judge score attached
- Judge output is human-readable: score + one-line reasoning per rubric field
- Scores stored in DB and queryable via CLI

---

### F4 — Monitoring + Alerting
**Metrics captured per call (Basic + Standard):**
- Total duration
- Turn count (agent + caller)
- First response latency (ms)
- Average turn latency (ms)
- Interruption count
- Sentiment (positive / neutral / negative — Claude-derived post-call)

**Alerting:**
- Configurable thresholds per agent (e.g. avg latency > 2s, sentiment = negative > 3 turns)
- Breach fires a webhook POST with call ID, metric, threshold, actual value
- Slack webhook is a stretch goal

**Acceptance criteria:**
- `shunya metrics summary <agent-id>` returns last 24h aggregate
- `shunya alerts create` configures a threshold via CLI
- Webhook fires within 30s of a threshold breach

---

### F5 — CLI (Control Plane)
Built with Typer. All commands wrap the DRF REST API.

```
shunya agents list
shunya agents create "..." --prompt "..."
shunya agents show <id>
shunya agents chat <id> "message"

shunya scenarios list
shunya scenarios show <name>

shunya tests run <agent-id> --scenario <name> --mode text|audio [--wait]
shunya tests list
shunya tests show <run-id>
shunya tests transcript <run-id> [--raw] [--no-color]
shunya tests audio <run-id> [--no-open]   # audio-mode recording link

shunya calls list
shunya calls transcript <call-id>
shunya calls metrics <call-id>
```

*(Actual command group is `tests`/`calls`/`agents`/`scenarios`; metrics/alerts are exposed via the REST API and monitoring app rather than dedicated CLI verbs in the current build.)*

**Acceptance criteria:**
- All commands have `--help`
- Auth via `SHUNYA_API_KEY` env var
- Non-zero exit code on API errors
- **Clean error UX:** missing key, bad ID (404), unauthorized (401/403), and unreachable server print a one-line `Error: …` message — no Python traceback (handled via `ShunyaError` + a `main()` wrapper)

---

### F6 — Call Recording (audio mode) — ✅ shipped

- Every audio-fidelity run is recorded: the caller bot mixes both sides (its own TTS + the agent's captured audio) into a mono 16 kHz WAV
- The file is written to a bind-mounted `./recordings/<run-id>.wav` and served by Django at `GET /recordings/<run-id>.wav` (content-type `audio/wav`, inline — plays in any browser)
- The serving view guards against path traversal and only serves `<name>.wav`

**Acceptance criteria:**
- After an audio run, `shunya tests transcript <run-id>` prints the recording link
- `shunya tests audio <run-id>` prints and opens the link in a browser (`--no-open` to suppress)
- Opening the URL plays the conversation inline

---

### F7 — Live listen-in (audio mode) — ✅ shipped

- The Pipecat `/connect` endpoint mints a non-owner **observer token** and returns an `observer_url` — a pre-authed Daily browser join link. Rooms are created with `max_participants: 10` (agent + caller + up to 8 human observers).
- The runner provisions the room *before* the scenario runs and persists the link to `TestRun.observer_url`.
- The CLI surfaces it live: `shunya tests run … --mode audio --wait` prints **👁 Join to observe: <url>** as soon as the run goes `running`, so a human can drop into the call while it happens.

**Acceptance criteria:**
- During a waited audio run, the CLI prints a join URL before the call completes
- Opening the URL in a browser joins the live Daily room and you can hear both bots

> **Live vs. recorded:** F7 (live listen-in) and F6 (recording) are complementary — observe in real time during the call, replay the durable WAV afterward. Only an *aggregate* "all calls" dashboard URL is out of scope (each call is its own ephemeral room).

---

## Out of Scope (MVP)

These were considered and deliberately deferred (see PLAN.md "Ideated & Parked" for full reasoning):

- Frontend dashboard (deferred — API is UI-ready)
- Phone / PSTN support
- **Aggregate "all calls" live dashboard** (per-run live listen-in shipped — see F7; only the single aggregate URL is deferred)
- **Voice Quirks *audio* synthesis** (rendering stutter/pause/noise as real audio; today only hard_input/email/phone are spoken verbatim in audio mode)
- **Stereo / multi-channel recording** (current is mono mix)
- Multi-dimension / panel LLM judge
- Advanced voice metrics (pitch, gibberish, diarization)
- Slack / email alerting (webhook shipped)
- SSO / OAuth

---

## Future Improvements

- **Aggregate "all calls" live dashboard** — a single page listing every in-progress call with one-click join (per-run live listen-in already shipped, see F7)
- **Voice Quirks audio synthesis** — render `[stutter]`/`[pause]`/`[background_noise]` as real audio in audio mode (today stripped)
- **Stereo recording** — separate caller/agent channels for diarization/analysis
- Multi-dimension LLM judge (per rubric field = separate Claude call)
- Panel-of-judges scoring (multi-model majority vote)
- Advanced metrics: pitch variance, gibberish score, speaker diarization
- React/Next.js dashboard + scenario web UI builder for non-engineers
- Slack + email alerting
- Phone / PSTN (Twilio) transport

---

## Constraints

- Django foundation (multi-tenant, schema-per-tenant via django-tenants) provided by Zenerate — integrate, don't replace
- All features must have `pytest` coverage
- API-first: every feature accessible via REST before CLI wraps it
- CallerInterface is the abstraction boundary — TextCaller and AudioCaller are both built; mode is a runtime parameter on each TestRun
- Audio fidelity mode requires a running Pipecat server and Daily.co credentials

---

## Open Questions (non-blocking, for Rohit)

| # | Question |
|---|---|
| Q2 | Does the Django foundation ship with auth + tenancy wired, or just base models? |
| Q3 | Preferred telephony provider when PSTN is added? |
| Q4 | "Housed similar to ElevenLabs" — confirm per-agent WebRTC endpoint pattern? |
