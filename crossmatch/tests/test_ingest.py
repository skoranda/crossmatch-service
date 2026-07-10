"""R8 / AE3: ingest_alert is idempotent per broker — a repeat delivery from the
same broker creates no duplicate, while a second broker records its own delivery."""

import pytest
from django.db import connection
from django.utils import timezone

from brokers import ingest_alert
from core.models import Alert, AlertDelivery


def _canonical(dia_id=9_100_000_001):
    return {
        "lsst_diaObject_diaObjectId": dia_id,
        "ra_deg": 180.0,
        "dec_deg": -30.0,
        "lsst_diaSource_diaSourceId": dia_id + 1,
        "event_time": timezone.now(),
        "payload": {"x": 1},
    }


@pytest.mark.django_db
def test_new_alert_created():
    assert ingest_alert(_canonical(), "antares") is True
    assert Alert.objects.count() == 1
    assert AlertDelivery.objects.count() == 1


@pytest.mark.django_db
def test_duplicate_same_broker_no_duplicate():
    # Covers AE3.
    canonical = _canonical()
    assert ingest_alert(canonical, "antares") is True
    assert ingest_alert(canonical, "antares") is False
    assert Alert.objects.count() == 1
    assert AlertDelivery.objects.filter(broker="antares").count() == 1


@pytest.mark.django_db
def test_second_broker_records_its_own_delivery():
    canonical = _canonical()
    assert ingest_alert(canonical, "antares") is True
    assert ingest_alert(canonical, "lasair") is True
    assert Alert.objects.count() == 1
    assert AlertDelivery.objects.count() == 2


@pytest.mark.django_db(transaction=True)
def test_ingest_recovers_from_severed_connection():
    """Regression: the broker consumers run as long-lived management-command
    loops with no request/response cycle, so Django never fires the
    request_started/request_finished signals that recycle DB connections. Once
    Postgres severed the cached connection, every later ORM query raised
    psycopg's "the connection is closed" until the pod restarted -- all three
    consumers (lasair, antares, pittgoogle) went dead on the shared ingest path.

    ingest_alert now recycles the connection per work unit, so a severed
    connection is dropped and reopened instead of reused. Sever the socket behind
    Django's back (Django still believes the cached connection is alive), then
    assert the next ingest succeeds. transaction=True runs the test outside a
    wrapping atomic block, matching the consumers' autocommit context so the
    recycle is not skipped by the in_atomic_block guard.
    """
    connection.ensure_connection()
    connection.connection.close()
    assert ingest_alert(_canonical(dia_id=9_100_000_777), "antares") is True
    assert Alert.objects.filter(lsst_diaObject_diaObjectId=9_100_000_777).exists()
