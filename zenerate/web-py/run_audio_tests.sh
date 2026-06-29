#!/usr/bin/env bash
# run_audio_tests.sh
# Purges all previous test runs and fires every scenario in audio mode.
# Usage: ./run_audio_tests.sh [agent-id]
# If agent-id is omitted the first agent in the demo tenant is used.

set -euo pipefail

TENANT="demo"
DJANGO_CONTAINER="shunya-django-1"

# Helper: run a manage.py shell snippet inside the Django container
django_shell() {
    docker exec "$DJANGO_CONTAINER" python manage.py shell -c "$1" 2>/dev/null
}

# ── 0. Sanity check ──────────────────────────────────────────────────────────
if ! docker inspect "$DJANGO_CONTAINER" &>/dev/null; then
    echo "ERROR: container '$DJANGO_CONTAINER' not found. Run: docker-compose up -d"
    exit 1
fi

# ── 1. Generate a fresh API key inside the container ────────────────────────
echo "==> Generating API key for tenant '$TENANT'..."
eval "$(django_shell "
from apps.tenants.models import TenantAPIKey, Tenant
t = Tenant.objects.get(schema_name='$TENANT')
obj, raw = TenantAPIKey.generate(t)
print(f'export SHUNYA_API_KEY={raw}')
" | grep '^export ')"
export SHUNYA_TENANT_HOST="${TENANT}.localhost"

# ── 2. Purge previous runs ────────────────────────────────────────────────────
echo "==> Purging previous test runs..."
django_shell "
from django_tenants.utils import schema_context
with schema_context('$TENANT'):
    from apps.testing.models import JudgeScore, TestResult, TestRun
    JudgeScore.objects.all().delete()
    TestResult.objects.all().delete()
    deleted, _ = TestRun.objects.all().delete()
    print(f'    Deleted {deleted} TestRun rows')
"

# ── 3. Resolve agent ID ───────────────────────────────────────────────────────
AGENT_ID="${1:-}"
if [[ -z "$AGENT_ID" ]]; then
    AGENT_ID=$(django_shell "
from django_tenants.utils import schema_context
with schema_context('$TENANT'):
    from apps.agents.models import Agent
    a = Agent.objects.first()
    print(a.id if a else '')
" | tail -1)
fi

if [[ -z "$AGENT_ID" ]]; then
    echo "ERROR: no agent found in tenant '$TENANT'. Create one with: shunya agents create"
    exit 1
fi
echo "==> Using agent: $AGENT_ID"

# ── 4. Load scenarios into DB (idempotent) ───────────────────────────────────
echo "==> Syncing scenarios..."
docker exec "$DJANGO_CONTAINER" python manage.py load_scenarios --dir /scenarios --schema "$TENANT" --force 2>&1 | grep -v "^26 objects" || true

# ── 5. Run all scenarios in audio mode (sequentially — each needs a Daily room) ─
SCENARIOS=(angry_customer_refund booking_happy_path edge_case_gibberish)
FAILED=0

for SCENARIO in "${SCENARIOS[@]}"; do
    echo ""
    echo "==> Running audio scenario: $SCENARIO"
    if ! shunya tests run "$AGENT_ID" --scenario "$SCENARIO" --mode audio --wait; then
        echo "    [FAILED] $SCENARIO"
        FAILED=$((FAILED + 1))
    fi
done

echo ""
if [[ $FAILED -eq 0 ]]; then
    echo "==> All audio runs completed successfully."
else
    echo "==> Done — $FAILED run(s) failed."
    exit 1
fi
