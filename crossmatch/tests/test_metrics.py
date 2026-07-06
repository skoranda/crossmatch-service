"""U6 / AE5: golden-signal metric-emission contract for core.metrics.

Covers the ingest counter + last-success gauge (via brokers.ingest_alert), the
Prometheus text-format exposition, and multiprocess aggregation (the prefork
Celery worker path). The crossmatch/notification counters are exercised through
their own task/notifier tests; here we pin the emission contract itself.
"""

import pytest
from django.utils import timezone

from brokers import ingest_alert
from core import metrics
from core.models import Alert


def _canonical(dia_id=9_200_000_001):
    return {
        "lsst_diaObject_diaObjectId": dia_id,
        "ra_deg": 180.0,
        "dec_deg": -30.0,
        "lsst_diaSource_diaSourceId": dia_id + 1,
        "event_time": timezone.now(),
        "payload": {"x": 1},
    }


def _counter(counter, **labels):
    return counter.labels(**labels)._value.get()


def _gauge(gauge, **labels):
    return gauge.labels(**labels)._value.get()


@pytest.mark.django_db
def test_ingest_increments_counter_and_advances_gauge():
    """Happy path: a successful ingest bumps the per-broker counter and advances
    the last-success gauge to a recent timestamp."""
    c_before = _counter(metrics.ALERTS_INGESTED, broker="antares", result="new")
    g_before = _gauge(metrics.INGEST_LAST_SUCCESS, broker="antares")

    assert ingest_alert(_canonical(), "antares") is True

    assert (
        _counter(metrics.ALERTS_INGESTED, broker="antares", result="new")
        == c_before + 1
    )
    assert _gauge(metrics.INGEST_LAST_SUCCESS, broker="antares") > g_before


@pytest.mark.django_db
def test_duplicate_ingest_counted_as_duplicate():
    """A repeat delivery is a successful processing: it increments the
    result='duplicate' counter (not 'new')."""
    canonical = _canonical(dia_id=9_200_000_050)
    ingest_alert(canonical, "antares")
    c_before = _counter(metrics.ALERTS_INGESTED, broker="antares", result="duplicate")

    assert ingest_alert(canonical, "antares") is False

    assert (
        _counter(metrics.ALERTS_INGESTED, broker="antares", result="duplicate")
        == c_before + 1
    )


@pytest.mark.django_db
def test_ingest_failure_does_not_advance_gauge(monkeypatch):
    """Edge: an ingest that raises before completion must not advance the
    last-success gauge."""
    g_before = _gauge(metrics.INGEST_LAST_SUCCESS, broker="lasair")

    def _boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(Alert.objects, "get_or_create", _boom)

    with pytest.raises(RuntimeError):
        ingest_alert(_canonical(dia_id=9_200_000_099), "lasair")

    assert _gauge(metrics.INGEST_LAST_SUCCESS, broker="lasair") == g_before


def test_render_metrics_returns_prometheus_text():
    """The exposition helper returns the registered series in Prometheus text
    format with the correct content type."""
    metrics.ALERTS_INGESTED.labels(broker="pittgoogle", result="new").inc()

    content_type, payload = metrics.render_metrics()
    body = payload.decode()

    assert content_type.startswith("text/plain")
    assert "crossmatch_alerts_ingested_total" in body


def test_multiprocess_render_aggregates(tmp_path, monkeypatch):
    """Multiprocess: two worker processes writing the same counter aggregate
    (sum), rather than one overwriting the other."""
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    from prometheus_client import Counter, values

    # Simulate two prefork children by binding the value backend to two pids.
    monkeypatch.setattr(values, "ValueClass", values.MultiProcessValue(lambda: 101))
    Counter("crossmatch_batches_total", "x", ["result"], registry=None).labels(
        result="completed"
    ).inc(2)
    monkeypatch.setattr(values, "ValueClass", values.MultiProcessValue(lambda: 202))
    Counter("crossmatch_batches_total", "x", ["result"], registry=None).labels(
        result="completed"
    ).inc(3)

    _, payload = metrics.render_metrics()
    body = payload.decode()

    assert 'crossmatch_batches_total{result="completed"} 5.0' in body
