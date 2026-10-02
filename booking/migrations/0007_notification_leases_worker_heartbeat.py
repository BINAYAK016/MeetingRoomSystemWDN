from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("booking", "0006_authentication_throttle_and_emailtoken_attempts")]

    operations = [
        migrations.AddField(model_name="notification", name="lease_token", field=models.UUIDField(blank=True, null=True)),
        migrations.AddField(model_name="notification", name="lease_expires_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AlterField(model_name="notification", name="status", field=models.CharField(choices=[("pending", "Pending"), ("sending", "Sending"), ("sent", "Sent"), ("failed", "Failed"), ("skipped", "Superseded")], default="pending", max_length=10)),
        migrations.CreateModel(name="WorkerHeartbeat", fields=[
            ("id", models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
            ("last_success_at", models.DateTimeField(blank=True, null=True)),
            ("last_error_at", models.DateTimeField(blank=True, null=True)),
        ], options={"db_table": "worker_heartbeat", "constraints": [models.CheckConstraint(condition=models.Q(id=1), name="worker_heartbeat_singleton")]}),
    ]
