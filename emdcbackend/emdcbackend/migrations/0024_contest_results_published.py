from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("emdcbackend", "0023_add_db_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="contest",
            name="results_published",
            field=models.BooleanField(default=False),
        ),
    ]
