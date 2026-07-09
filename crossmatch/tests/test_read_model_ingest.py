"""U3 / R2, R3, R4, R5: per-broker reliability extraction at normalize time, and
first-seen reliability + computed healpix_ipix at ingest.

- AE1: reliability read from the broker-specific path; null when the key is absent.
- AE2: first delivery's reliability is frozen; later deliveries do not update it.
- AE3 (storage half): a payload lacking the key persists reliability=None.
"""

import pytest
from django.utils import timezone

from brokers import ingest_alert
from brokers.normalize import (
    normalize_antares,
    normalize_lasair,
    normalize_pittgoogle,
)
from core.healpix import radec_to_ipix
from core.models import Alert


class _PittGoogleAlert:
    """Minimal stand-in for the Pitt-Google client alert (exposes .dict)."""

    def __init__(self, payload):
        self.dict = payload


def _antares_raw(reliability=0.8):
    raw = {
        "lsst_diaObject_diaObjectId": 9_200_000_001,
        "lsst_diaObject_ra": 180.0,
        "lsst_diaObject_dec": -30.0,
        "lsst_diaSource_diaSourceId": 9_200_000_002,
        "ant_time_received": 1_700_000_000.0,
    }
    if reliability is not None:
        raw["lsst_diaSource_reliability"] = reliability
    return raw


def _lasair_raw(reliability=0.75):
    raw = {
        "diaObjectId": 9_300_000_001,
        "ra": 12.0,
        "decl": -5.0,
        "firstDiaSourceMjdTai": 60000.0,
    }
    if reliability is not None:
        raw["latestR"] = reliability
    return raw


def _pittgoogle_payload(reliability=0.9):
    dia_source = {"diaSourceId": 9_400_000_002, "midpointMjdTai": 60000.0}
    if reliability is not None:
        dia_source["reliability"] = reliability
    return {
        "diaObject": {"diaObjectId": 9_400_000_001, "ra": 200.0, "dec": 10.0},
        "diaSource": dia_source,
    }


# ── AE1: per-broker extraction path map ──────────────────────────────────────

def test_antares_reliability_from_flat_key():
    assert normalize_antares(_antares_raw(0.83))["reliability"] == 0.83


def test_lasair_reliability_from_latestr():
    assert normalize_lasair(_lasair_raw(0.71))["reliability"] == 0.71


def test_pittgoogle_reliability_from_nested_key():
    alert = _PittGoogleAlert(_pittgoogle_payload(0.92))
    assert normalize_pittgoogle(alert)["reliability"] == 0.92


def test_missing_reliability_key_yields_none():
    assert normalize_antares(_antares_raw(None))["reliability"] is None
    assert normalize_lasair(_lasair_raw(None))["reliability"] is None
    assert normalize_pittgoogle(_PittGoogleAlert(_pittgoogle_payload(None)))["reliability"] is None


# ── AE2: first-seen reliability freeze + ipix at ingest ──────────────────────

def _canonical(dia_id=9_500_000_001, reliability=None, ra_deg=100.0, dec_deg=-45.0):
    return {
        "lsst_diaObject_diaObjectId": dia_id,
        "ra_deg": ra_deg,
        "dec_deg": dec_deg,
        "lsst_diaSource_diaSourceId": dia_id + 1,
        "event_time": timezone.now(),
        "reliability": reliability,
        "payload": {"x": 1},
    }


@pytest.mark.django_db
def test_reliability_is_frozen_first_seen():
    # Covers AE2.
    ingest_alert(_canonical(reliability=0.70), "antares")
    ingest_alert(_canonical(reliability=0.90), "lasair")
    alert = Alert.objects.get(lsst_diaObject_diaObjectId=9_500_000_001)
    assert alert.reliability == 0.70


@pytest.mark.django_db
def test_ipix_computed_at_ingest_and_frozen_first_seen():
    ingest_alert(_canonical(reliability=0.70, ra_deg=100.0, dec_deg=-45.0), "antares")
    alert = Alert.objects.get(lsst_diaObject_diaObjectId=9_500_000_001)
    expected = radec_to_ipix(100.0, -45.0)
    assert alert.healpix_ipix == expected
    # A repeat delivery reporting DIFFERENT coordinates does not recompute or
    # change ipix — it stays frozen at the first delivery's position.
    ingest_alert(_canonical(reliability=0.90, ra_deg=250.0, dec_deg=10.0), "lasair")
    alert.refresh_from_db()
    assert alert.healpix_ipix == expected
    assert alert.healpix_ipix != radec_to_ipix(250.0, 10.0)


@pytest.mark.django_db
def test_null_reliability_persists_as_none():
    # Covers AE3 (storage half): a payload with no reliability stores NULL.
    ingest_alert(_canonical(reliability=None), "lasair")
    alert = Alert.objects.get(lsst_diaObject_diaObjectId=9_500_000_001)
    assert alert.reliability is None
    assert alert.healpix_ipix is not None


@pytest.mark.django_db
def test_out_of_range_coordinate_stores_null_ipix_without_dropping_alert():
    # A declination beyond the pole must not abort ingest (cdshealpix would
    # raise/panic); healpix_ipix degrades to NULL and the alert still persists.
    assert (
        ingest_alert(
            _canonical(dia_id=9_600_000_001, ra_deg=10.0, dec_deg=95.0), "antares"
        )
        is True
    )
    alert = Alert.objects.get(lsst_diaObject_diaObjectId=9_600_000_001)
    assert alert.healpix_ipix is None
