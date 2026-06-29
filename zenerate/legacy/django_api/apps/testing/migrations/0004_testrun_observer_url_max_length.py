from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("testing", "0003_scenario_compatible_agents"),
    ]

    operations = [
        migrations.AlterField(
            model_name="testrun",
            name="observer_url",
            field=models.URLField(blank=True, default="", max_length=500),
        ),
    ]
