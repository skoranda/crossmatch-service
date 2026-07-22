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
their age). A production rollout on a live, actively-ingesting table should still run
this in a quiet window — see the retention plan (KTD2).

Uses a **keyset loop, not a streaming ``.iterator()``**: this migration is
``atomic=False`` so it can commit each chunk incrementally on the live ~110 GB table,
but a COMMIT closes a WITHOUT-HOLD server-side cursor, which would break a long-lived
``.iterator()`` mid-run (``InvalidCursorName``) and abort ``migrate``. Instead, each
pass re-selects a bounded pk slice; setting ``notified_at`` drops those rows out of
the ``notified_at__isnull=True`` predicate, so the loop terminates without tracking
an offset and never holds a cursor across a commit.
"""

from django.db import migrations
from django.db.models import Exists, F, OuterRef, Q

BATCH_SIZE = 5000


def backfill_notified_at(apps, schema_editor):
    Alert = apps.get_model('core', 'Alert')
    Notification = apps.get_model('core', 'Notification')

    unsent = Notification.objects.filter(
        alert_id=OuterRef('lsst_diaObject_diaObjectId')
    ).exclude(state='sent')

    terminal = Alert.objects.filter(notified_at__isnull=True).filter(
        Q(status='NOTIFIED') | (Q(status='MATCHED') & ~Exists(unsent))
    )

    while True:
        pks = list(terminal.values_list('pk', flat=True)[:BATCH_SIZE])
        if not pks:
            break
        Alert.objects.filter(pk__in=pks).update(notified_at=F('ingest_time'))


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
