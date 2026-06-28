"""Initial migration: Tenant table.

RLS policies for tenant-scoped tables are NOT in migrations. They are
emitted by the ``post_migrate`` signal in ``models.py``, which runs after
every migration and re-syncs policies for every model that declares
``RowLevelSecurityMeta``.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Tenant",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=200)),
                ("slug", models.SlugField(max_length=64, unique=True)),
                ("service_token", models.CharField(max_length=128, unique=True)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "db_table": "multitenant_tenant",
                "ordering": ("name",),
            },
        ),
    ]
