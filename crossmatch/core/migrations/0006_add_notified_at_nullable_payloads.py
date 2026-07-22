"""Add ``Alert.notified_at`` and make the two payload columns nullable.

All three operations are catalog-only metadata changes (PostgreSQL 11+): adding a
nullable column with no default and dropping ``NOT NULL`` do not rewrite the table,
so this is fast even on the live ~110 GB DEV / production ``core_alert`` table.

The retention-query index on ``notified_at`` is deliberately created in a separate,
non-atomic migration (0007) with ``CREATE INDEX CONCURRENTLY`` so it never takes an
``ACCESS EXCLUSIVE`` lock on the live table. See the payload-retention plan (KTD2).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_add_ingest_time_index'),
    ]

    operations = [
        migrations.AddField(
            model_name='alert',
            name='notified_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='alert',
            name='payload',
            field=models.JSONField(null=True),
        ),
        migrations.AlterField(
            model_name='notification',
            name='payload',
            field=models.JSONField(null=True),
        ),
    ]
