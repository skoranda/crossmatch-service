# Btree index on Alert.ingest_time so the recent-crossmatch API's default
# (ingest_time) window is index-backed, mirroring core_alert_event_time_idx.
#
# Blocking trade-off: this is a plain AddIndex (CREATE INDEX, not CONCURRENTLY),
# which takes an ACCESS EXCLUSIVE lock and blocks writes on the actively-ingesting
# Alert table for the build duration. On DEV that is acceptable — the table is a
# single-column btree over ~1.8M rows (a brief build), migrations apply
# unattended via manage.py locked_init at consumer startup, and prior read-model
# index migrations (0003) added the same way without incident. A production
# build on a much larger live table should instead use
# django.contrib.postgres.operations.AddIndexConcurrently with atomic = False;
# that is deferred ops work, intentionally out of scope for the DEV rollout.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_backfill_healpix_ipix'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='alert',
            index=models.Index(fields=['ingest_time'], name='core_alert_ingest_time_idx'),
        ),
    ]
