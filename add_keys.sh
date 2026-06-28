#!/usr/bin/env bash
set -e

ZSHRC="$HOME/.zshrc"

echo "Generating SHUNYA_API_KEY (via Docker)..."
SHUNYA_API_KEY=$(
  docker-compose exec -T django python manage.py shell -c "
from apps.tenants.models import Tenant, TenantAPIKey
t = Tenant.objects.get(schema_name='demo')
_, raw = TenantAPIKey.generate(t)
print(raw)
" 2>/dev/null | tail -1
)

if [ -z "$SHUNYA_API_KEY" ]; then
  echo "ERROR: Could not generate key. Is 'docker-compose up' running?"
  exit 1
fi

# Remove any previous Shunya CLI block from .zshrc to avoid duplicates
sed -i '' '/# ── Shunya CLI/,/# ────/d' "$ZSHRC" 2>/dev/null || true

cat >> "$ZSHRC" << EOF

# ── Shunya CLI ────────────────────────────────────────────────────────────────
export SHUNYA_API_KEY="${SHUNYA_API_KEY}"
export SHUNYA_TENANT_HOST="demo.localhost"
# ────────────────────────────────────────────────────────────────────────────
EOF

echo "Done. Key prefix: ${SHUNYA_API_KEY:0:8}"
echo "Run: source ~/.zshrc"

