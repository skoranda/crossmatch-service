"""Create the retention-sweep index on ``Alert.notified_at`` concurrently.

Partial index (only rows still carrying a payload) that the retention sweep uses to
find past-grace terminal alerts. Built with ``CREATE INDEX CONCURRENTLY`` in a
non-atomic migration so it never takes an ``ACCESS EXCLUSIVE`` lock on the live
``core_alert`` table (KTD2). ``AddIndexConcurrently`` cannot run inside a
transaction, hence ``atomic = False``.
"""

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ('core', '0006_add_notified_at_nullable_payloads'),
    ]

    operations = [
        AddIndexConcurrently(
            model_name='alert',
            index=models.Index(
                fields=['notified_at'],
                name='core_alert_notified_at_idx',
                condition=models.Q(payload__isnull=False),
            ),
        ),
    ]
