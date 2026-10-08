from django.db import migrations, models


def restore_previous_meeting_types(apps, schema_editor):
    reservation = apps.get_model("booking", "Reservation")
    # Mixed meetings retain their external guest information if this UI change is rolled back.
    reservation.objects.using(schema_editor.connection.alias).filter(meeting_type="mixed").update(
        meeting_type="external"
    )


class Migration(migrations.Migration):
    dependencies = [("booking", "0008_booking_approval")]

    operations = [
        migrations.RemoveConstraint(model_name="reservation", name="external_meeting_has_company"),
        migrations.AlterField(
            model_name="reservation",
            name="meeting_type",
            field=models.CharField(
                choices=[
                    ("internal", "Internal"),
                    ("external", "External"),
                    ("mixed", "Internal + External"),
                ],
                default="internal",
                max_length=8,
            ),
        ),
        migrations.AddConstraint(
            model_name="reservation",
            constraint=models.CheckConstraint(
                condition=models.Q(kind="block")
                | models.Q(meeting_type="internal")
                | (models.Q(meeting_type__in=["external", "mixed"]) & ~models.Q(guest_company_name="")),
                name="external_meeting_has_company",
            ),
        ),
        migrations.RunPython(migrations.RunPython.noop, restore_previous_meeting_types),
    ]
