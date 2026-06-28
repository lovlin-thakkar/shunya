# Take-Home Baseline: `web-py`

Real, runnable Django 5.2 + DRF + Postgres + RLS baseline. **Layout matches the production zenafide `web-py` repo** so anything you build here drops back without path changes.

```
web-py/                                # workspace root
├── pyproject.toml                     # UV workspace (apps/api + packages/agent + packages/mt)
├── ruff.toml
├── .gitignore
│
├── apps/api/                          # ── Django app ──
│   ├── pyproject.toml                 # Django + DRF + Knox + workspace deps
│   ├── manage.py
│   ├── docker-compose.yml             # Postgres 17 + Redis 7.2
│   ├── .env.example
│   ├── src/zenapi/
│   │   ├── asgi.py
│   │   ├── wsgi.py
│   │   └── config/
│   │       ├── settings/__init__.py   # middleware wired, RLS-ready
│   │       ├── urls.py
│   │       └── url_confs/
│   │           ├── urls.py            # base (health, auth, admin)
│   │           └── email.py           # mounts email_pipeline.urls
│   └── tests/
│       ├── conftest.py                # tenant_a, tenant_b, in_tenant, service_headers
│       ├── factories.py               # TenantFactory
│       ├── test_multitenant.py        # reference cross-tenant denial test
│       └── email_pipeline/            # YOUR app's tests live here
│
└── packages/
    ├── mt/                            # ── internal library, DO NOT MODIFY ──
    │   ├── pyproject.toml
    │   └── src/zenlib/
    │       ├── reusable_apps/multitenant/
    │       │   ├── apps.py
    │       │   ├── context.py         # current_tenant ContextVar
    │       │   ├── models.py          # Tenant, TenantAwareMixin, ActivityTenantBaseModel
    │       │   ├── managers.py        # AutoFilteringManager, *AutoFilter classes
    │       │   ├── middleware.py      # MultitenantContext + RLS middlewares
    │       │   ├── settings.py        # CONF_NAME_*, default_rls_options
    │       │   └── migrations/0001_initial.py
    │       └── django_utils/db/pg_rls/
    │           ├── __init__.py        # re-exports
    │           └── policies.py        # Policy, policy builders, RLS SQL helpers
    │
    └── agent/                         # ── YOUR APP LIVES HERE ──
        ├── pyproject.toml
        └── src/zenlib_agentos/zenlib/reusable_apps/email_pipeline/
            ├── apps.py
            ├── authentication.py      # ServiceTokenAuthentication (provided)
            ├── urls.py                # empty DRF router; register your viewsets
            ├── models/__init__.py     # add models here
            ├── serializers/__init__.py
            ├── views/__init__.py
            ├── services/__init__.py
            ├── admin/__init__.py
            └── migrations/__init__.py
```

## Setup

```bash
cd apps/api
docker compose up -d db
cd ../..

uv sync --all-packages
cd apps/api && uv run python manage.py migrate
uv run python manage.py runserver 8000
```

Test:

```bash
uv run pytest -q                       # multitenant reference tests must pass
```

## What you must build (Phase 1)

1. **Models** under `packages/agent/src/zenlib_agentos/zenlib/reusable_apps/email_pipeline/models/`:
   `LogicalThread`, `RoleInboxLink`, `Message`, `ProcessedEvent`. All inherit `ActivityTenantBaseModel` from `zenlib.reusable_apps.multitenant.models`.
2. **Serializers** under `serializers/`.
3. **Views** under `views/`. Use `IsServiceAccount` from `email_pipeline.authentication` for service-only writes.
4. **Register routes** in `email_pipeline/urls.py` (DRF router scaffolded).
5. **Run migrations** — `cd apps/api && uv run python manage.py makemigrations email_pipeline && uv run python manage.py migrate`.
6. **Cross-tenant test** in `apps/api/tests/email_pipeline/test_rls.py` — model after `test_multitenant.py`.

## What you must NOT touch

- `packages/mt/` — internal library. File a bug in your README's "decisions log" and route around it if needed.
- `MIDDLEWARE` order in `apps/api/src/zenapi/config/settings/__init__.py` — `MultitenantContextMiddleware` must precede `MultitenantRLSMiddleware`.
- The `Tenant` model — it's the multitenant root.

## RLS in one paragraph

Every model inheriting `ActivityTenantBaseModel` gets a Postgres row-level security policy attached automatically (via the `post_migrate` signal in `zenlib.reusable_apps.multitenant.models`). At request time, `MultitenantRLSMiddleware` runs `SET LOCAL app.current_tenant_id = <id>` on the connection. Postgres then transparently filters rows to that tenant on every `SELECT`/`INSERT`/`UPDATE`/`DELETE`. You do not write RLS migration SQL — the base class handles it. Verify it works (see `tests/test_multitenant.py`).
