from django.db import migrations


def create_initial_policy(apps, schema_editor):
    policy = apps.get_model("booking", "BookingPolicy")
    policy.objects.using(schema_editor.connection.alias).get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [("booking", "0001_initial")]

    operations = [migrations.RunPython(create_initial_policy, migrations.RunPython.noop)]
