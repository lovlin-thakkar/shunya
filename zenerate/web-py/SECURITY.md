# Security Review

Findings from internal review of the Shunya voice AI QA platform. Ranked by criticality.

---

## Critical

### 1. Unauthenticated recording access
**File:** `apps/api/src/zenapi/config/urls.py` (lines 10–20)

`/recordings/<filename>` is fully public — no auth, no tenant check. Anyone who knows or guesses a run UUID can download another tenant's call recording.

**Fix:** Require `Authorization: Api-Key` on this endpoint and verify the recording's `TestRun.agent.tenant == current_tenant` before serving.

---

### 2. SSRF via webhook URLs — ✅ RESOLVED
**File:** `packages/agent/src/zenlib_agentos/zenlib/reusable_apps/voice_qa/services/metrics.py`

`AlertConfig.webhook_url` is a raw user-supplied URL. When a call ends, the `compute_call_metrics` Celery worker evaluates the agent's alerts and POSTs to this URL directly. A malicious tenant could set it to internal targets: `http://postgres:5432`, `http://redis:6379`, `http://169.254.169.254` (cloud metadata), etc.

**Resolution:** `_fire_alert()` now calls `_is_safe_webhook_url()` before every POST. It rejects non-http(s) schemes, the hostnames `localhost`/`metadata.google.internal`/`169.254.169.254`, and any hostname that resolves to a private/loopback/link-local/reserved address. Blocked URLs are logged and skipped; the `AlertEvent` is still recorded. Verified manually: a `127.0.0.1` webhook is blocked.

**Residual risk:** DNS-rebinding (the host resolves to a public IP at check time, a private one at request time) is not covered, since the resolve-and-connect are separate. Acceptable for now; revisit if alerts move off the trusted internal network.

---

### 3. Pipecat server has no authentication
**File:** `services/voice/server.py` (lines 73, 138)

`/connect` and `/caller/run` on `:8001` accept requests from anyone with network access — no token, no origin check. An attacker who can reach the port can spawn unlimited Daily.co rooms and drain ElevenLabs/Daily quotas.

**Fix:** Check `X-Service-Token` header on both endpoints (same token the Django internal API uses). Currently mitigated by Docker network isolation but not safe if the port is ever exposed.

---

## High

### 4. Cross-tenant `_chat_sessions` cache
**File:** `packages/agent/src/zenlib_agentos/zenlib/reusable_apps/voice_qa/views/__init__.py` (lines 34–37)

Module-level dict keyed only on `conversation_id`, not `(tenant_id, conversation_id)`. Two tenants using the same conversation ID share an `AgentChat` instance and each other's message history.

**Fix:** Key the cache as `f"{tenant.id}:{conversation_id}"`.

---

### 5. No explicit tenant filter in ViewSet querysets
**File:** `packages/agent/src/zenlib_agentos/zenlib/reusable_apps/voice_qa/views/__init__.py` — all `get_queryset()` methods

All ViewSets rely solely on Postgres RLS for isolation. No application-level `.filter(tenant=...)`. If RLS middleware is misconfigured, skipped, or disabled, all tenant data is exposed with no fallback.

**Fix:** Add `.filter(tenant=context.current_tenant.get())` to every `get_queryset()` as defence-in-depth.

---

### 6. Hardcoded fallback secrets
**File:** `apps/api/src/zenapi/config/settings/__init__.py` (lines 17, 108)

`SECRET_KEY` and `SERVICE_TOKEN` both have `"dev-..."` string defaults. If the env vars are missing in production, Django silently uses predictable keys — forged sessions, bypassed service auth.

**Fix:** Raise `django.core.exceptions.ImproperlyConfigured` when `DEBUG=False` and either key matches the dev default.

---

### 7. `/debug-ws` endpoint leaks ElevenLabs API key
**File:** `services/voice/server.py` (lines 177–195)

An unprotected WebSocket debug route that exposes `ELEVENLABS_API_KEY` in headers/logs.

**Fix:** Delete it. No debug endpoints in production code.

---

## Medium

### 8. No rate limiting
Entire Django API has no throttling. Any authenticated tenant can spam `POST /api/v1/test-runs/` to exhaust Anthropic tokens and Celery workers.

**Fix:** Add DRF throttling — `UserRateThrottle` at `DEFAULT_THROTTLE_CLASSES` in `REST_FRAMEWORK` settings. Three lines of config.

---

### 9. Internal endpoints don't verify tenant on agent lookup
**File:** `packages/agent/src/zenlib_agentos/zenlib/reusable_apps/voice_qa/urls/internal.py` (lines 24, 69)

`ServiceTokenAuthentication` is a single global secret. If pipecat is compromised, it can create calls for agents belonging to any tenant by passing an arbitrary `agent_id`.

**Fix:** After looking up the agent, assert `agent.tenant_id == int(request.headers["X-Tenant-Id"])`.

---

### 10. CORS credentials enabled
**File:** `apps/api/src/zenapi/config/settings/__init__.py` (lines 124–125)

`CORS_ALLOW_CREDENTIALS = True`. Currently safe because `CORS_ALLOWED_ORIGINS` is a single explicit origin. If ever relaxed to multiple origins or a pattern match, it opens CSRF attack surface.

**Fix:** Keep as-is but add explicit note; don't widen `CORS_ALLOWED_ORIGINS` without reviewing.

---

## Notes

- Items 1, 2, 4 are the highest-priority real bugs in a multi-tenant context.
- Items 3, 5, 6 are hardening improvements.
- Items 7–10 are good practice but low exploitability in current deployment.
