"""Backfill ``Alert.notified_at`` for existing terminal alerts.

Brings pre-existing terminal rows under payload retention: a NULL ``notified_at``
is never caught by the retention sweep, so every already-terminal alert needs one.

Terminal alerts are:
  * ``NOTIFIED`` alerts, and
  * ``MATCHED`` alerts with no unsent notification (no-match alerts have zero
    notifications; others may have all notifications already SENT).
``MATCHED`` alerts that still have a PENDING/FAILED notification are in flight and
are left NULL, so their payloads stay until they actually reach a terminal state.

``notified_at`` is set to ``ingest_time`` (a defensible floor — the alert became
terminal shortly after ingest, and for existing rows the grace math is dominated by
their age). Chunked and non-atomic so it commits incrementally and never holds one
long transaction on the live table; the ``ACCESS EXCLUSIVE``-free index already
exists from 0007. Mirrors ``0004_backfill_healpix_ipix.py``. A production rollout on
a live, actively-ingesting table should still run this in a quiet window — see the
retention plan (KTD2).
"""

from django.db import migrations
from django.db.models import Exists, OuterRef, Q

BATCH_SIZE = 5000


def backfill_notified_at(apps, schema_editor):
    Alert = apps.get_model('core', 'Alert')
    Notification = apps.get_model('core', 'Notification')

    unsent = Notification.objects.filter(
        alert_id=OuterRef('lsst_diaObject_diaObjectId')
    ).exclude(state='sent')

    queryset = (
        Alert.objects.filter(notified_at__isnull=True)
        .filter(Q(status='NOTIFIED') | (Q(status='MATCHED') & ~Exists(unsent)))
        .only('pk', 'ingest_time', 'notified_at')
    )

    batch = []
    for alert in queryset.iterator(chunk_size=BATCH_SIZE):
        alert.notified_at = alert.ingest_time
        batch.append(alert)
        if len(batch) >= BATCH_SIZE:
            Alert.objects.bulk_update(batch, ['notified_at'], batch_size=BATCH_SIZE)
            batch = []
    if batch:
        Alert.objects.bulk_update(batch, ['notified_at'], batch_size=BATCH_SIZE)


def noop_reverse(apps, schema_editor):
    """Reverse is a no-op: notified_at is a derived anchor, safe to leave populated."""


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ('core', '0007_notified_at_index_concurrent'),
    ]

    operations = [
        migrations.RunPython(backfill_notified_at, noop_reverse),
    ]
