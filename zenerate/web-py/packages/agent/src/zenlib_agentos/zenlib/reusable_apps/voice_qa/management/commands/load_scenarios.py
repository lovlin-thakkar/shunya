from pathlib import Path

import yaml
from django.core.management.base import BaseCommand
from django.db import connection

from zenlib.reusable_apps.multitenant import context
from zenlib.reusable_apps.multitenant.models import Tenant

from ...models import Agent, Scenario
from ...services.quirks import parse_step


def _set_rls(tenant_id: int):
    """Set Postgres RLS GUC for the current session (management commands skip middleware)."""
    with connection.cursor() as cur:
        cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", [str(tenant_id)])


class Command(BaseCommand):
    help = "Load YAML scenario files into the database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dir",
            default=str(Path(__file__).resolve().parents[9] / "scenarios"),
            help="Directory containing YAML scenario files",
        )
        parser.add_argument("--force", action="store_true", help="Overwrite existing scenarios")
        parser.add_argument("--tenant", default=None, help="Tenant slug or id to load into (default: first tenant)")

    def handle(self, *args, **options):
        tenant_arg = options.get("tenant")
        if tenant_arg:
            try:
                tenant = Tenant.objects.get(slug=tenant_arg)
            except Tenant.DoesNotExist:
                tenant = Tenant.objects.get(id=int(tenant_arg))
        else:
            tenant = Tenant.objects.first()
        if tenant is None:
            self.stderr.write("No tenant found. Create one first.")
            return
        context.current_tenant.set(tenant)
        _set_rls(tenant.id)
        self.stdout.write(f"Loading into tenant: {tenant.name} (id={tenant.id})")

        scenarios_dir = Path(options["dir"])
        if not scenarios_dir.exists():
            self.stderr.write(f"Directory not found: {scenarios_dir}")
            return

        files = list(scenarios_dir.glob("*.yaml")) + list(scenarios_dir.glob("*.yml"))
        if not files:
            self.stdout.write("No YAML files found.")
            return

        for f in files:
            raw_text = f.read_text()
            data = yaml.safe_load(raw_text)
            name = data["name"]
            steps = [parse_step(s) for s in data.get("steps", [])]
            # Pass tenant explicitly — UUID PKs with default=uuid4 pre-set self.pk,
            # which causes ActivityTenantBaseModel._populate_tenant_if_needed to bail early.
            agent_names = data.get("agents", [])
            defaults = {
                "tenant": tenant,
                "description": data.get("description", ""),
                "yaml_content": raw_text,
                "persona": data.get("persona", ""),
                "steps": steps,
                "assertions": data.get("assertions", []),
                "rubric": data.get("rubric", {}),
            }
            if options["force"]:
                obj, created = Scenario.objects.update_or_create(name=name, defaults=defaults)
            else:
                obj, created = Scenario.objects.get_or_create(name=name, defaults=defaults)

            # Sync compatible_agents M2M from the YAML agents list.
            if created or options["force"]:
                linked = Agent.objects.filter(name__in=agent_names)
                obj.compatible_agents.set(linked)

            if created:
                verb = "Created"
            elif options["force"]:
                verb = "Updated"
            else:
                verb = "Skipped (use --force to update)"
            self.stdout.write(f"{verb}: {name}")

        self.stdout.write(self.style.SUCCESS(f"Done. Processed {len(files)} scenario(s)."))
