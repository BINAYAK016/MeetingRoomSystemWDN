from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("booking", "0010_room_photo")]

    operations = [
        migrations.AddField(
            model_name="room",
            name="requires_approval",
            field=models.BooleanField(default=True),
        ),
    ]
