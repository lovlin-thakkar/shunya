from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("testing", "0002_add_observer_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="scenario",
            name="compatible_agents",
            field=models.JSONField(default=list),
        ),
    ]
