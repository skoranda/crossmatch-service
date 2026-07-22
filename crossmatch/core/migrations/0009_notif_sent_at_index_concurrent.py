"""Create the retention-sweep index on ``Notification.sent_at`` concurrently.

Mirror of the alert-side index (0007): a partial index over rows still carrying a
payload, so the notification half of the retention sweep is as cheap and
self-limiting as the alert half. Built with ``CREATE INDEX CONCURRENTLY`` in a
non-atomic migration so it never takes an ``ACCESS EXCLUSIVE`` lock on the live
``core_notification`` table.
"""

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ('core', '0008_backfill_notified_at'),
    ]

    operations = [
        AddIndexConcurrently(
            model_name='notification',
            index=models.Index(
                fields=['sent_at'],
                name='core_notif_sent_at_idx',
                condition=models.Q(payload__isnull=False),
            ),
        ),
    ]
