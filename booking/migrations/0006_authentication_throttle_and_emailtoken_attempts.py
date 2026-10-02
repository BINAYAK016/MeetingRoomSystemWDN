from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("booking", "0005_booking_policy_valid_limits"),
    ]

    operations = [
        migrations.AddField(
            model_name="user", name="auth_version",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="emailtoken", name="attempts",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.CreateModel(
            name="AuthenticationThrottle",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("purpose", models.CharField(max_length=40)),
                ("key", models.CharField(max_length=64)),
                ("window_started_at", models.DateTimeField()),
                ("attempts", models.PositiveIntegerField(default=0)),
            ],
            options={
                "db_table": "authentication_throttles",
                "indexes": [models.Index(fields=["window_started_at"], name="auth_throttle_window_idx")],
                "constraints": [models.UniqueConstraint(fields=("purpose", "key"), name="auth_throttle_purpose_key_unique")],
            },
        ),
    ]
