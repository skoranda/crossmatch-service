"""U1 / R1, R5, R7: the Alert read-model columns persist and round-trip, and the
three read-model btree indexes exist after migration."""

import pytest
from django.db import connection

from core.models import Alert
from tests.factories import AlertFactory


@pytest.mark.django_db
def test_alert_persists_with_null_read_model_fields():
    alert = AlertFactory()
    alert.refresh_from_db()
    assert alert.reliability is None
    assert alert.healpix_ipix is None


@pytest.mark.django_db
def test_alert_round_trips_read_model_fields():
    alert = AlertFactory(reliability=0.7, healpix_ipix=123456)
    alert.refresh_from_db()
    assert alert.reliability == 0.7
    assert alert.healpix_ipix == 123456


@pytest.mark.django_db
def test_read_model_indexes_present():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = %s",
            [Alert._meta.db_table],
        )
        index_names = {row[0] for row in cursor.fetchall()}
    assert {
        "core_alert_reliability_idx",
        "core_alert_event_time_idx",
        "core_alert_healpix_ipix_idx",
        "core_alert_ingest_time_idx",
    } <= index_names
