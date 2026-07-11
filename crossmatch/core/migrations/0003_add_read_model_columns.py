from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_alert_queued_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='alert',
            name='reliability',
            field=models.FloatField(null=True),
        ),
        migrations.AddField(
            model_name='alert',
            name='healpix_ipix',
            field=models.BigIntegerField(null=True),
        ),
        migrations.AddIndex(
            model_name='alert',
            index=models.Index(fields=['reliability'], name='core_alert_reliability_idx'),
        ),
        migrations.AddIndex(
            model_name='alert',
            index=models.Index(fields=['event_time'], name='core_alert_event_time_idx'),
        ),
        migrations.AddIndex(
            model_name='alert',
            index=models.Index(fields=['healpix_ipix'], name='core_alert_healpix_ipix_idx'),
        ),
    ]
