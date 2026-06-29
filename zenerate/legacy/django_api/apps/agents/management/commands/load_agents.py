from pathlib import Path

import yaml
from django.core.management.base import BaseCommand

from apps.agents.models import Agent


class Command(BaseCommand):
    help = "Load YAML agent definition files into the database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dir",
            default=str(Path(__file__).resolve().parents[5] / "agents"),
            help="Directory containing YAML agent files (default: <repo>/agents/)",
        )
        parser.add_argument(
            "--schema",
            default=None,
            help="Tenant schema name to load agents into (e.g. 'demo')",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite existing agents with the same name",
        )

    def handle(self, *args, **options):
        schema = options.get("schema")
        if schema:
            from django_tenants.utils import schema_context
            with schema_context(schema):
                self._load(options)
        else:
            self._load(options)

    def _load(self, options):
        agents_dir = Path(options["dir"])
        if not agents_dir.exists():
            self.stderr.write(f"Directory not found: {agents_dir}")
            return

        files = list(agents_dir.glob("*.yaml")) + list(agents_dir.glob("*.yml"))
        if not files:
            self.stdout.write("No YAML files found.")
            return

        for f in files:
            raw = f.read_text()
            data = yaml.safe_load(raw)
            name = data["name"]

            defaults = {
                "description": data.get("description", ""),
                "system_prompt": data.get("system_prompt", ""),
                "greeting": data.get("greeting", ""),
                "voice_id": data.get("voice_id", ""),
                "yaml_content": raw,
            }

            if options["force"]:
                obj, created = Agent.objects.update_or_create(name=name, defaults=defaults)
            else:
                obj, created = Agent.objects.get_or_create(name=name, defaults=defaults)

            if created:
                verb = "Created"
            elif options["force"]:
                verb = "Updated"
            else:
                verb = "Skipped (use --force to update)"
            self.stdout.write(f"{verb}: {name}")

        self.stdout.write(self.style.SUCCESS(f"Done. Processed {len(files)} agent(s)."))
