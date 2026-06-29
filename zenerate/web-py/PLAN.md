# Shunya — Product Scoping Document

> **How to use this doc**: Each section is a decision. Review the options, pros, and cons, then tell Claude your choice. Once all decisions are made, this file becomes the locked PRD.

> **⚠️ Status note (post-build):** The decision tables below capture the *original* scoping. Several decisions changed during implementation — see **[Amendments During Build](#amendments-during-build)** at the bottom for what actually shipped and why. The most important pivots: **STT is ElevenLabs Scribe v2** (not Deepgram), **the agent brain is Claude Haiku 4.5** (not GPT-4o), **audio fidelity mode shipped** (was Phase 2), and **the whole stack is Docker-first** (forced by `daily-python` not supporting Python 3.14).

---

## Background: What We're Building

A simplified in-house version of [Cekura.ai](https://www.cekura.ai) — an automated QA + monitoring platform for voice AI agents. Think: "Datadog + Playwright, but for voice agents."

Two deliverables:
1. **A voice agent** — a real Pipecat-powered voice agent (Daily WebRTC + STT + LLM + ElevenLabs TTS). *(Originally scoped as Deepgram + GPT-4o; shipped as ElevenLabs Scribe v2 + Claude Haiku 4.5 — see Amendments.)* Humans can call it; it also serves as the system under test for audio fidelity mode.
2. **The Cekura platform** — automated testing in two modes, monitoring, and evaluation. Multi-tenant, API-first, CLI-driven.

Foundation: Multi-tenant Django + Postgres (provided by Zenerate, arriving soon).

> **Two test modes (mirrors Cekura exactly):**
> - **Text mode** (default) — TextCaller injects text directly into the agent's LLM (Claude Haiku). Fast, parallel, no audio. Voice Quirks DSL simulates speech conditions.
> - **Audio fidelity mode** — AudioCaller (Pipecat bot) synthesizes speech, joins the voice agent's Daily.co room, has a real voice conversation. Tests the full STT → LLM → TTS stack.

---

---

# DECISION TABLES

---

## D1 — Voice Agent Transport
*How does a caller connect to the voice agent?*

| # | Option | Pros | Cons | Best For |
|---|---|---|---|---|
| A | **WebRTC only** (Daily.co / LiveKit) | No telephony cost, instant setup, browser-testable, Pipecat's native path | Can't call from a real phone; requires browser or SDK client | Dev/demo environments, web-first products |
| B | **Phone/PSTN only** (Twilio / Vonage) | Real phone number, anyone can call, closest to production voice agents | Costs per minute, slower setup, harder to automate test calls | Consumer voice products, phone-first UX |
| C | **Both** (WebRTC + Phone bridge) | Maximum flexibility; test via WebRTC, demo via phone | Double the integration surface, more infra to manage | Production-grade platforms |

**Decision:** ___

---

## D2 — Speech-to-Text (STT) Provider
*Which service transcribes caller audio to text?*

| # | Option | Pros | Cons | Best For |
|---|---|---|---|---|
| A | **Deepgram Nova-3** | Lowest latency (~200ms), streaming, best accuracy for English, free tier | Paid beyond free tier, less multilingual | Real-time voice agents where latency matters most |
| B | **OpenAI Whisper (API)** | High accuracy, strong multilingual, familiar brand | Batch-only (no streaming), higher latency (~1-2s), costs more | Post-call transcription, non-real-time analysis |
| C | **AssemblyAI** | Good accuracy, built-in sentiment + speaker diarization, streaming available | More expensive per minute, smaller community | When you want bundled analytics (sentiment, speakers) |

**Decision:** ___

---

## D3 — Text-to-Speech (TTS) Provider
*Which service turns agent text responses into audio?*

| # | Option | Pros | Cons | Best For |
|---|---|---|---|---|
| A | **ElevenLabs** | Best voice quality, most natural, huge voice library, Pipecat-native integration | Most expensive, latency ~400-800ms first chunk | Showcasing voice quality; assessment explicitly mentions ElevenLabs |
| B | **Cartesia** | Ultra-low latency (~90ms), good quality, newer | Smaller voice library, less known | Latency-sensitive agents |
| C | **OpenAI TTS** | Good quality, cheap, familiar API | No streaming in real-time chunks, less natural than ElevenLabs | Budget builds, prototypes |

**Decision:** ___

---

## D4 — LLM for the Voice Agent Brain
*Which model powers the agent's responses?*

| # | Option | Pros | Cons | Best For |
|---|---|---|---|---|
| A | **Claude claude-sonnet-4-6** | Excellent instruction-following, strong tool use, low hallucination, great for structured agent prompts | Slightly higher cost than GPT-3.5, Anthropic API key needed | Assessment context (Zenerate likely uses Anthropic stack) |
| B | **GPT-4o mini** | Very fast, cheap, good quality, huge ecosystem | Weaker at following complex system prompts vs Claude | Cost-sensitive, high-volume agents |
| C | **Gemini 2.0 Flash** | Fast, cheap, long context, Google ecosystem | Less proven for structured voice agent use cases | Multimodal use cases |

**Decision:** ___

---

## D5 — QA Test Caller Approach
*How does the platform simulate a user calling the agent?*

| # | Option | Pros | Cons | Best For |
|---|---|---|---|---|
| A | **Pipecat bot-to-bot** (full audio loop) | Most realistic — actual audio is synthesized and sent through the pipeline; catches audio-layer bugs | Complex to set up, resource-intensive, requires WebRTC between two bots | True voice QA where audio quality matters |
| B | **Text-level simulation** (bypass audio, inject text directly) | Fast, cheap, parallelizable, easy to assert on | Skips STT/TTS entirely — won't catch audio pipeline bugs | Functional/LLM behavior testing at scale |
| C | **Hybrid** (text-level by default, audio mode on demand) | Best of both — fast CI runs + deep audio tests when needed | More engineering effort to build both modes | Production-grade QA platform |

**Decision:** ___

---

## D6 — Test Scenario Definition Format
*How are test scenarios authored and stored?*

| # | Option | Pros | Cons | Best For |
|---|---|---|---|---|
| A | **YAML DSL** (files in repo) | Git-versioned, familiar to engineers, easy to diff/review, fast to author | Non-technical users can't author scenarios, no UI | Engineering-first teams |
| B | **JSON via API** (scenarios stored in DB) | API-driven, programmable, integrates with CI pipelines | Verbose to author by hand, no human-readable format | Platform integrations, CI/CD workflows |
| C | **Both: YAML loaded into DB** | Author in YAML, execute from DB — best ergonomics | More parsing logic needed | Teams that want git-based workflow + API execution |

**Decision:** ___

---

## D7 — LLM Judge Design
*How does the platform evaluate conversation quality?*

| # | Option | Pros | Cons | Best For |
|---|---|---|---|---|
| A | **Single Claude call with rubric** | Simple, fast, cheap, easy to reason about | Single model = single point of failure; less robust scoring | MVP / assessment — good enough to demonstrate the concept |
| B | **Multi-dimension rubric** (one Claude call per metric: accuracy, helpfulness, tone, safety) | More granular scores, easier to debug which dimension failed | 3-5x more API calls per evaluation | Production QA where you need per-dimension reporting |
| C | **Panel of judges** (multiple model calls, majority vote) | Most robust, reduces model bias | Expensive, slow, overkill for an assessment | Enterprise QA with high-stakes agents |

**Decision:** ___

---

## D8 — Monitoring Metrics Scope
*What do we measure on every call?*

| # | Option | Pros | Cons | Best For |
|---|---|---|---|---|
| A | **Basic** — latency per turn, total duration, turn count, pass/fail | Fast to implement, covers the fundamentals | Doesn't differentiate from a simple logger | Proving the concept quickly |
| B | **Standard** — A + interruption count, sentiment (Claude-derived), first response latency, word count per turn | Good balance of depth and effort; demonstrates voice-specific thinking | Sentiment via LLM adds cost/latency to post-call pipeline | Strong assessment submission |
| C | **Advanced** — B + pitch detection, gibberish score, background noise flag, speaker diarization | Matches real Cekura feature set; impressive | Requires audio processing libraries (librosa, pyannote), significant extra complexity | Differentiated, senior-level showcase |

**Decision:** ___

---

## D9 — Multi-Tenancy Model
*How is data isolated between tenants?*

| # | Option | Pros | Cons | Best For |
|---|---|---|---|---|
| A | **Row-level** (`tenant_id` FK on every table) | Simple, single DB schema, easy to query across tenants for analytics | Risk of data leak if queries miss the tenant filter; need to audit every query | Small-scale, faster to build |
| B | **Schema-per-tenant** (django-tenants) | Strong isolation, no leakage risk, scales well | More complex migrations, can't query across tenants easily | Production SaaS, compliance-heavy |
| C | **Middleware-enforced row-level** (with Django middleware that auto-filters all queries) | Good isolation with simpler schema than B, middleware handles the filtering | Middleware magic can be hard to debug | Balance of safety and simplicity |

**Decision:** ___

---

## D10 — Alerting Channels
*Where do alerts go when a metric threshold is breached?*

| # | Option | Pros | Cons | Best For |
|---|---|---|---|---|
| A | **Webhook only** | Universal — anything that receives HTTP can subscribe; simple to implement | Users must set up their own Slack/PagerDuty connection | Developers, platform integrations |
| B | **Slack + Webhook** | Slack is where most dev teams live; webhook for extensibility | Need Slack app setup, two integrations to build | Team-facing dashboards |
| C | **Slack + Email + Webhook** | Matches real Cekura's feature set; covers all personas | Most work to implement; email setup (SMTP/SendGrid) adds config burden | Full feature parity demo |

**Decision:** ___

---

## D11 — CLI Scope
*What can the CLI do?*

| # | Option | Pros | Cons | Best For |
|---|---|---|---|---|
| A | **Read-only** — list agents, view calls, query metrics | Simple to build, safe, good for observability workflows | Can't trigger test runs or configure alerts from CLI | Ops/monitoring use cases |
| B | **Control plane** — A + trigger test runs, create scenarios, configure alerts | Full power tool; showcases thinking about developer UX | More surface area to build and test | Senior engineer showcase |
| C | **Control plane + interactive** — B + `shunya init` wizard, `shunya login`, config file | Most polished; feels like a real SaaS CLI | Significant extra effort for the auth/config layer | Product-level CLI (Vercel, Railway style) |

**Decision:** ___

---

## D12 — Frontend Strategy
*Is there a dashboard UI, and what stack?*

| # | Option | Pros | Cons | Best For |
|---|---|---|---|---|
| A | **Defer entirely** — API + CLI only | Maximum focus on backend depth; CLI is a first-class interface | No visual demo; harder to showcase monitoring in a walkthrough | If CLI + API are demo'd live |
| B | **Django + HTMX** — server-rendered dashboard | Fast to build, no context switching, stays in Django monolith | Less impressive visually; HTMX not widely known | Tight timeline |
| C | **React + Next.js** (separate app, calls DRF API) | Most impressive, industry-standard, decoupled | More setup, two repos/apps to manage | If you want the full SaaS feel |

**Decision:** ___

---

---

# LOCKED DECISIONS

| Decision | Choice | Notes |
|---|---|---|
| D1 — Transport | **A — WebRTC only (Daily.co)** | Active. Used by both the voice agent (humans calling it) and audio fidelity test mode (AudioCaller bot joins the room). |
| D2 — STT | ~~A — Deepgram Nova-3~~ → **ElevenLabs Scribe v2** | **Changed during build.** Consolidated on a single voice vendor (ElevenLabs already does TTS) — one API key, one bill, comparable quality. The agent pipeline uses Pipecat's `ElevenLabsSTTService` (Scribe streaming); the synthetic caller transcribes the agent's audio with the Scribe v2 REST endpoint. Deepgram dropped entirely. |
| D3 — TTS | **A — ElevenLabs** | Active. Used in both voice agent (agent speaks to humans) and AudioCaller (bot synthesizes caller speech). **Gotcha learned:** `output_format` must be a **query param**, not a JSON body field — in the body it's ignored and ElevenLabs returns MP3. |
| D4 — Agent LLM | ~~GPT-4o~~ → **Claude Haiku 4.5** (`claude-haiku-4-5-20251001`) | **Changed during build.** "One AI for agent + QA" — the agent brain and the LLM judge both run on the Anthropic stack (one SDK, one key). Haiku is fast/cheap for the agent; the judge uses Sonnet 4.6. Dropped the OpenAI SDK dependency. |
| D5 — QA Test Caller | **C — Hybrid (Text mode + Audio fidelity mode)** | Locked **and both shipped**. Text mode = default (TextCaller, fast, parallel). Audio fidelity = a `ScenarioCallerBot` (separate Pipecat service) joins the Daily room and has a real bot-to-bot voice conversation. Audio mode was originally scoped as "Phase 2" but was fully built. |
| D6 — Scenario Format | **A — YAML DSL** | Locked. Git-versioned, engineer-friendly, loaded into DB at runtime. |
| D7 — LLM Judge | **A — Single Claude call with rubric** | Locked. Multi-dimension + panel → Future Improvements. |
| D8 — Metrics Scope | **A/B — Basic + Standard** | Locked. Latency, turns, duration, interruptions, sentiment, first-response latency. Advanced (pitch, gibberish, diarization) → Future Improvements. |
| D9 — Multi-Tenancy | **B — Schema-per-tenant (django-tenants)** | Locked (assumed, pending confirmation from Rohit on what foundation ships). Will pivot if foundation uses row-level. |
| D10 — Alerting | **A — Webhook** | Locked. Slack optional/stretch goal. |
| D11 — CLI Scope | **B — Control plane** | Locked. list + trigger test runs + configure alerts + view results. |
| D12 — Frontend | **A — Defer** | Locked. API + CLI only. Dashboard is future work. |

---

## D5 — OPEN: QA Test Caller Approach

**Proposed approach (your idea):** Text-level simulation with a lightweight **Voice Quirks DSL** embedded in caller turns. Instead of full audio bots, the synthetic caller sends annotated text that the test runner interprets to simulate realistic speech behaviors.

**Example DSL annotations:**
```
[pause:3s] I'm not sure what I mean by that...
[stutter] Can you re-re-repeat that?
[background_noise] Hello? Can you hear me?
[interrupt] Wait, actually—
[accent:southern] I'd like to book a appointment
[slow_speech] I... need... help... with... my... account
```

**How it works:** The test runner strips annotations before sending to STT/LLM, but logs them as simulated conditions alongside the transcript. The LLM judge is told what conditions were active when scoring.

**Pros of this approach:**
- Fast and parallelizable (no audio to process)
- Still captures behavioral edge cases (interruptions, hesitation, accents)
- Novel — differentiates from a standard Pipecat bot-to-bot setup
- Can run 100 scenarios in the time a bot-to-bot runs 5

**Cons:**
- Doesn't test the actual STT layer (Deepgram won't see real audio artifacts)
- "Accent" is simulated in text, not real audio — not a true audio fidelity test

**Recommendation to discuss with Rohit:** Frame this as the default test mode (fast, scalable), with a future "audio fidelity mode" (full Pipecat bot-to-bot) as a Phase 2 feature. This is actually more innovative than standard bot-to-bot and makes a stronger demo.

---

## OPEN QUESTIONS FOR ROHIT

| # | Question | Context |
|---|---|---|
| Q1 | ~~D5: Voice Quirks DSL vs audio bot-to-bot?~~ | **RESOLVED** — Text DSL locked, audio mode is Phase 2. |
| Q2 | **Will the Django foundation include auth/multi-tenancy already wired, or just the base models?** | Affects how much time to spend on tenant scaffolding vs feature depth. |
| Q3 | **Is there a preferred telephony provider if phone/PSTN support is needed later?** | We've chosen WebRTC-only for now; want to confirm this is acceptable scope for the assessment. |
| Q4 | **What does "housed similar to ElevenLabs" mean exactly for the voice agent?** | ElevenLabs exposes agents via WebSocket/API with a per-agent endpoint. Confirming this is the pattern expected. |
| Q5 | ~~D9: Schema-per-tenant vs row-level?~~ | **RESOLVED** — django-tenants assumed; will pivot if foundation ships differently. |

---

## FUTURE IMPROVEMENTS (post-MVP, document for the write-up)

These are explicitly deferred but should be called out in the PRD to show awareness:

| Feature | Why Deferred | Value When Built |
|---|---|---|
| **Multi-dimension LLM Judge** (per-metric: accuracy, tone, safety, helpfulness) | Adds 3-5x API calls per eval; overkill for MVP | Granular per-dimension scores for QA reports |
| **Panel of judges** (multi-model majority vote) | Expensive + complex; not needed to prove concept | Removes single-model bias; enterprise QA grade |
| **Advanced voice metrics** (pitch, gibberish score, speaker diarization, background noise) | Requires audio processing libs (librosa, pyannote); significant effort | True Cekura parity; differentiates from text-based QA |
| **Audio fidelity test mode** (full Pipecat bot-to-bot with real audio) — **Phase 2** | Complex infra; architecture designed to plug in without rewriting the test runner | Tests the actual STT layer; catches audio-pipeline bugs text DSL can't simulate |
| **Voice demo layer** (Pipecat + Daily.co + Deepgram + ElevenLabs) | Not needed for QA platform; the agent brain is transport-agnostic | Lets real humans call the agent via browser; full voice experience |
| **Slack / email alerting** | Webhook covers the core use case | Reduces friction for non-technical stakeholders |
| **React/Next.js dashboard** | Deferred to keep focus on backend depth | Visual demo, metric charts, scenario browser |
| **Scenario web UI builder** | YAML DSL covers the engineering use case | Non-technical persona/scenario authoring |
| **Phone/PSTN support** (Twilio) | WebRTC-only is sufficient for assessment | Real phone number for demos and consumer products |

---

---

## DECISION SUMMARY — ALL 12 LOCKED

| Decision | Original Choice | As Shipped |
|---|---|---|
| D1 — Transport | WebRTC only (Daily.co) | ✅ Same |
| D2 — STT | Deepgram Nova-3 | 🔄 **ElevenLabs Scribe v2** |
| D3 — TTS | ElevenLabs | ✅ Same |
| D4 — Agent LLM | GPT-4o | 🔄 **Claude Haiku 4.5** |
| D5 — QA Test Caller | Hybrid (text + audio) | ✅ Both shipped (audio was "Phase 2") |
| D6 — Scenario Format | YAML DSL | ✅ Same (YAML → DB via `load_scenarios`) |
| D7 — LLM Judge | Single Claude call with rubric | ✅ Same (Sonnet 4.6, 0.0–1.0 scoring) |
| D8 — Metrics Scope | Basic + Standard | ✅ Same |
| D9 — Multi-Tenancy | Schema-per-tenant (django-tenants) | ✅ Same |
| D10 — Alerting | Webhook (Slack optional/stretch) | ✅ Webhook shipped; Slack/email parked |
| D11 — CLI Scope | Control plane | ✅ Same (+ clean error handling, recording links) |
| D12 — Frontend | Deferred — API + CLI only | ✅ Still deferred |

---

# Amendments During Build

Decisions and architecture choices that emerged or changed *while building*, with the reasoning:

### A1 — STT: Deepgram → ElevenLabs Scribe v2
We already depended on ElevenLabs for TTS. Adding Deepgram meant a second vendor, key, and bill for marginal benefit. ElevenLabs Scribe v2 covers both the agent's streaming STT and the synthetic caller's transcription of the agent. **One voice vendor, one key.**

### A2 — Agent brain: GPT-4o → Claude Haiku 4.5
"Use a single AI for agent + QA." The judge was always Claude; moving the agent brain to Claude too means one SDK, one API key, one mental model. Haiku 4.5 is fast/cheap enough for real-time voice; the judge stays on Sonnet 4.6.

### A3 — Deployment: local processes → Docker-first
`daily-python` (the Daily SDK) has no wheels for **Python 3.14** (the local interpreter) and panics natively. Rather than juggle a second local Python, we containerised the whole stack and pinned the voice containers to **`python:3.12`**. The Pipecat/caller images also force `--platform=linux/amd64` because `daily-python`'s native lib misbehaves on ARM64. `docker-compose up` is now the canonical way to run everything.

### A4 — Audio caller: in-process → separate `caller` service
`daily-python` cannot host two `CallClient`s (or call `Daily.init()` twice) in one process. The agent pipeline already owns one. So the synthetic caller runs as its **own FastAPI service/container** (`caller_server.py` on :8002), which the Pipecat server calls over HTTP. Clean process isolation, no native crashes.

### A5 — Audio fidelity mode shipped (was "Phase 2")
Originally parked as future work. We built it end-to-end: `ScenarioCallerBot` joins the room, speaks each step (ElevenLabs TTS → Daily virtual mic), captures the agent's audio (Daily virtual speaker → Scribe v2), and returns a transcript. Getting it working surfaced seven distinct root causes (Python version, ARM64, Pipecat 1.4 API changes, double Daily.init, empty voice_id → malformed URL → 403, thread-affine device writes, and **MP3-instead-of-PCM** because `output_format` was in the request body instead of the query string). See RUNBOOK §15 for the full list.

### A6 — Call recording + browser playback (new feature)
Since the caller bot already holds both audio streams in memory, we mix them into a mono 16 kHz WAV per run, write it to a bind-mounted `./recordings`, and serve it at `http://localhost:8000/recordings/<run-id>.wav`. Surfaced in the CLI (`shunya tests audio <run-id>`).

### A7 — Live listen-in shipped (was originally parked)
Initially evaluated against recording and parked. We then built it because the cost was trivial: `/connect` already creates the Daily room, so it now also mints a non-owner **observer token** and returns an `observer_url` (a pre-authed browser join link). The room is created with `max_participants: 10` (agent + caller + up to 8 human observers). The runner provisions the room *before* the scenario starts, persists the link to `TestRun.observer_url` (migrations 0002/0004), and the CLI prints **👁 Join to observe** as soon as a `--wait` poll sees the run go `running`. Live listen-in (during the call) and the recording (after) are complementary, not alternatives.

---

## Ideated & Parked (deliberately not built)

| Idea | Status | Why parked |
|---|---|---|
| **"All calls" live dashboard** (one URL listing every in-progress call to drop into) | Parked | Each call is its own ephemeral Daily room, so there's no single aggregate URL. Per-run live listen-in *was* shipped (see A7); only the aggregate dashboard view is deferred. |
| **Voice Quirks audio synthesis** (actually render `[stutter]`/`[pause]`/`[background_noise]` as audio in audio mode) | Parked | Today these tags are stripped in audio mode; only `[hard_input]`/`[email]`/`[phone]` values are spoken verbatim. Real audio synthesis of disfluencies is a meaningful effort for marginal QA value right now. |
| **Stereo recording** (separate caller/agent channels) | Parked | Current mix is mono (half-duplex conversation reads fine). Stereo would aid diarization/analysis later. |
| **HTTP range requests on the recordings endpoint** (seek within large files) | Parked | WAVs are short; full download + inline play is fine. |
| **Multi-dimension / panel LLM judge** | Future | 3–5× the API calls; single-call rubric proves the concept. |
| **Advanced voice metrics** (pitch, gibberish, diarization) | Future | Needs `librosa`/`pyannote`; significant complexity. |
| **React/Next.js dashboard** | Future | API + CLI cover the demo; keeps focus on backend depth. |
| **Scenario web UI builder** | Future | YAML DSL covers the engineering persona. |
| **Phone / PSTN** (Twilio) | Future | WebRTC-only is sufficient for the assessment. |
| **Slack / email alerting** | Future | Webhook covers the core path. |

**Status: All 12 original decisions resolved; six amendments (A1–A6) applied during build. Audio fidelity mode and call recording shipped beyond original scope.**
