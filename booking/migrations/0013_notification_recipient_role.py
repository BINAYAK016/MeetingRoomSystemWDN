from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("booking", "0012_department")]

    operations = [
        migrations.AddField(
            model_name="notification",
            name="recipient_role",
            field=models.CharField(
                choices=[
                    ("legacy", "Legacy audience"),
                    ("participant", "Meeting participant"),
                    ("front_desk", "Front desk"),
                ],
                default="legacy",
                max_length=12,
            ),
        ),
    ]
