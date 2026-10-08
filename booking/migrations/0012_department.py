from django.db import migrations, models
from django.db.models.functions import Lower

INITIAL_DEPARTMENTS = (
    "Accounts",
    "Administrative",
    "Logistics",
    "Sales",
    "Oracle Support",
    "Dell Support",
    "Toshiba",
    "ATM support",
)


def populate_departments(apps, schema_editor):
    alias = schema_editor.connection.alias
    departments = apps.get_model("booking", "Department").objects.using(alias)
    for name in INITIAL_DEPARTMENTS:
        departments.get_or_create(name=name)
    # Existing labels remain selectable without changing profiles or booking history.
    for model_name in ("User", "Reservation"):
        labels = (
            apps.get_model("booking", model_name)
            .objects.using(alias)
            .exclude(department="")
            .values_list("department", flat=True)
            .distinct()
            .order_by("department")
        )
        for label in labels.iterator():
            name = label.strip()
            if name and not departments.filter(name__iexact=name).exists():
                departments.create(name=name)


class Migration(migrations.Migration):
    dependencies = [("booking", "0011_room_requires_approval")]

    operations = [
        migrations.CreateModel(
            name="Department",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("name", models.CharField(max_length=120)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "db_table": "departments",
                "ordering": ["name"],
                "constraints": [models.UniqueConstraint(Lower("name"), name="departments_name_ci_unique")],
            },
        ),
        migrations.RunPython(populate_departments, migrations.RunPython.noop),
    ]
