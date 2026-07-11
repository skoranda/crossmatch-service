"""Backfill ``healpix_ipix`` for rows that predate the read-model columns.

``ipix`` is cheap and deterministic from the stored coordinates, so the whole
existing corpus is populated here in batches (vectorized per batch to avoid a
per-row native call across ~1M rows). ``reliability`` is deliberately left NULL
on existing rows — it is forward-only per the plan's Product Contract.

Note: this migration builds indexes and updates in the ordinary (atomic) way,
which is fine for DEV. A production rollout on the live table should create
indexes with ``CREATE INDEX CONCURRENTLY`` and commit backfill batches
incrementally; that ops step is out of scope for this data-layer migration.
"""

from django.db import migrations

# Modest batch size for the live ~1M-row table: one bulk_update round-trip and
# one vectorized ipix computation per batch.
BATCH_SIZE = 5000


def backfill_healpix_ipix(apps, schema_editor):
    Alert = apps.get_model('core', 'Alert')
    queryset = (
        Alert.objects.filter(healpix_ipix__isnull=True)
        .only('uuid', 'ra_deg', 'dec_deg', 'healpix_ipix')
    )

    batch = []
    for alert in queryset.iterator(chunk_size=BATCH_SIZE):
        batch.append(alert)
        if len(batch) >= BATCH_SIZE:
            _flush(Alert, batch)
            batch = []
    if batch:
        _flush(Alert, batch)


def _flush(Alert, batch):
    from core.healpix import radec_to_ipix_array

    ipix = radec_to_ipix_array(
        [alert.ra_deg for alert in batch],
        [alert.dec_deg for alert in batch],
    )
    for alert, pixel in zip(batch, ipix):
        alert.healpix_ipix = pixel
    Alert.objects.bulk_update(batch, ['healpix_ipix'], batch_size=BATCH_SIZE)


def noop_reverse(apps, schema_editor):
    """Reverse is a no-op: healpix_ipix is a derived column, safe to leave populated."""


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_add_read_model_columns'),
    ]

    operations = [
        migrations.RunPython(backfill_healpix_ipix, noop_reverse),
    ]
