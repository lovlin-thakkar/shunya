from pathlib import Path

import yaml
from django.core.management.base import BaseCommand

from ...models import Scenario
from ...services.quirks import parse_step


class Command(BaseCommand):
    help = "Load YAML scenario files into the database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dir",
            default=str(Path(__file__).resolve().parents[7] / "scenarios"),
            help="Directory containing YAML scenario files",
        )
        parser.add_argument("--force", action="store_true", help="Overwrite existing scenarios")

    def handle(self, *args, **options):
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
            defaults = {
                "description": data.get("description", ""),
                "yaml_content": raw_text,
                "persona": data.get("persona", ""),
                "steps": steps,
                "assertions": data.get("assertions", []),
                "rubric": data.get("rubric", {}),
                "compatible_agents": data.get("agents", []),
            }
            if options["force"]:
                obj, created = Scenario.objects.update_or_create(name=name, defaults=defaults)
            else:
                obj, created = Scenario.objects.get_or_create(name=name, defaults=defaults)

            if created:
                verb = "Created"
            elif options["force"]:
                verb = "Updated"
            else:
                verb = "Skipped (use --force to update)"
            self.stdout.write(f"{verb}: {name}")

        self.stdout.write(self.style.SUCCESS(f"Done. Processed {len(files)} scenario(s)."))
