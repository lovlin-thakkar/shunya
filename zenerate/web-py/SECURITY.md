# Security Review

Findings from internal review of the Shunya voice AI QA platform. Ranked by criticality.

---

## Critical

### 1. Unauthenticated recording access
**File:** `apps/api/src/zenapi/config/urls.py` (_RecordingView)

`/recordings/<filename>` is fully public — no auth, no tenant check. Anyone who knows or guesses a run UUID can download another tenant's call recording.

**Fix:** Require `Authorization: Api-Key` on this endpoint and verify the recording's `TestRun.agent.tenant == current_tenant` before serving.

---

### 2. SSRF via webhook URLs — ✅ RESOLVED
**File:** `packages/agent/src/zenlib_agentos/zenlib/reusable_apps/voice_qa/services/metrics.py`

`AlertConfig.webhook_url` is a raw user-supplied URL. When a call ends, the `compute_call_metrics` Celery worker evaluates alerts and POSTs to this URL directly. A malicious tenant could set it to internal targets.

**Resolution:** `_fire_alert()` calls `_is_safe_webhook_url()` before every POST. It rejects non-http(s) schemes, `localhost`, `metadata.google.internal`, `169.254.169.254`, and any hostname resolving to private/loopback/link-local/reserved addresses.

**Residual risk:** DNS-rebinding not covered; acceptable for now.

---

### 3. Pipecat server has no authentication
**File:** `services/voice/server.py`

`/connect` and `/caller/run` on `:8001` accept requests from anyone with network access — no token, no origin check. An attacker who can reach the port can spawn unlimited Daily.co rooms.

**Fix:** Check `X-Service-Token` header on both endpoints. Currently mitigated by Docker network isolation.

---

## High

### 4. Cross-tenant `_chat_sessions` cache
**File:** `packages/agent/src/zenlib_agentos/zenlib/reusable_apps/voice_qa/views/__init__.py`

Module-level dict keyed only on `conversation_id`, not `(tenant_id, conversation_id)`. Two tenants using the same conversation ID share an `AgentChat` instance.

**Fix:** Key the cache as `f"{tenant.id}:{conversation_id}"`.

---

### 5. No explicit tenant filter in ViewSet querysets
**File:** `packages/agent/src/zenlib_agentos/zenlib/reusable_apps/voice_qa/views/__init__.py` — all `get_queryset()`

All ViewSets rely solely on Postgres RLS for isolation. No application-level `.filter(tenant=...)`. If RLS middleware is misconfigured or skipped, all tenant data is exposed.

**Fix:** Add `.filter(tenant=context.current_tenant.get())` to every `get_queryset()` as defence-in-depth.

---

### 6. Hardcoded fallback secrets
**File:** `apps/api/src/zenapi/config/settings/__init__.py` (lines 17, 117)

`SECRET_KEY` and `SERVICE_TOKEN` both have `"dev-..."` string defaults. If env vars are missing in production, Django uses predictable keys.

**Fix:** Raise `ImproperlyConfigured` when `DEBUG=False` and either key matches the dev default. **Already implemented** (lines 152–155).

---

### 7. `/debug-ws` endpoint leaks ElevenLabs API key
**File:** `services/voice/server.py`

An unprotected WebSocket debug route that exposes `ELEVENLABS_API_KEY`.

**Fix:** Delete it. No debug endpoints in production code. **Already removed.**

---

## Medium

### 8. Rate limiting
**File:** `packages/agent/src/zenlib_agentos/zenlib/reusable_apps/voice_qa/throttling.py`

Django API now has `ScopedIdentityUserRateThrottle` wired (300/min for `user` scope). Pipecat :8001 has 5 concurrent pipeline limit; caller :8002 has 4 concurrent remote run limit.

**Fix:** Add DRF throttling. **Partially addressed** — `ScopedIdentityUserRateThrottle` wired at settings level.

---

### 9. Internal endpoints don't verify tenant on agent lookup
**File:** `packages/agent/src/zenlib_agentos/zenlib/reusable_apps/voice_qa/urls/internal.py`

`ServiceTokenAuthentication` is a single global secret. If pipecat is compromised, it can create calls for agents belonging to any tenant.

**Fix:** After looking up the agent, assert `agent.tenant_id == int(request.headers["X-Tenant-Id"])`.

---

### 10. CORS credentials enabled
**File:** `apps/api/src/zenapi/config/settings/__init__.py`

`CORS_ALLOW_CREDENTIALS = True`. Currently safe because `CORS_ALLOWED_ORIGINS` is a single explicit origin.

**Fix:** Keep as-is; don't widen `CORS_ALLOWED_ORIGINS` without reviewing.

---

## Notes

- Items 1, 2, 4 are the highest-priority real bugs in a multi-tenant context.
- Items 3, 5, 6 are hardening improvements.
- Items 7–10 are good practice but low exploitability in current deployment.
