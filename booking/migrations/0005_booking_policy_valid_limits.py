from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("booking", "0004_remove_emailtoken_email_token_purpose_target_valid_and_more"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="bookingpolicy",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    minimum_minutes__gt=0,
                    maximum_minutes__lte=1440,
                    slot_minutes__lte=60,
                    gap_minutes__lte=120,
                    advance_days__lte=366,
                    check_in_minutes__gt=0,
                    check_in_minutes__lte=models.F("minimum_minutes"),
                ),
                name="booking_policy_valid_limits",
            ),
        ),
    ]
