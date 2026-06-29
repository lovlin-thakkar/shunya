from django.core.management.base import BaseCommand, CommandError
from zenlib.reusable_apps.multitenant.models import Tenant
from zenlib.reusable_apps.multitenant import context
from zenlib_agentos.zenlib.reusable_apps.voice_qa.models import TenantAPIKey


class Command(BaseCommand):
    help = "Generate a CLI API key for a tenant"

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant",
            default=None,
            help="Tenant name (defaults to the first tenant)",
        )

    def handle(self, *args, **options):
        tenant_name = options["tenant"]
        if tenant_name:
            try:
                tenant = Tenant.objects.get(name=tenant_name)
            except Tenant.DoesNotExist:
                raise CommandError(f"Tenant '{tenant_name}' not found")
        else:
            tenant = Tenant.objects.first()
            if tenant is None:
                raise CommandError(
                    "No tenants exist. Create one first:\n"
                    "  python manage.py shell -c \"from zenlib.reusable_apps.multitenant.models import Tenant; Tenant.objects.create(name='default')\""
                )

        context.current_tenant.set(tenant)
        _, raw_key = TenantAPIKey.generate(tenant)

        self.stdout.write(f"Tenant : {tenant.name}")
        self.stdout.write(f"Key ID : {tenant.id}")
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("export SHUNYA_API_KEY=" + raw_key))
        self.stdout.write(self.style.SUCCESS("export SHUNYA_BASE_URL=http://localhost:8000"))
