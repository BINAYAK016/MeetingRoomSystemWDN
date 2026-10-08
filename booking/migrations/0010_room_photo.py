from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("booking", "0009_mixed_meeting_type")]

    operations = [
        migrations.AddField(
            model_name="room", name="photo",
            field=models.ImageField(blank=True, upload_to="rooms/photos/"),
        ),
    ]
