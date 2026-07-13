"""U4 / R5, R4: the 0004 data migration backfills healpix_ipix for existing rows
from their stored coordinates, leaves reliability untouched, is safe to re-run,
and reverses as a no-op."""

import importlib

import pytest
from django.apps import apps as global_apps

from core.healpix import radec_to_ipix
from core.models import Alert
from tests.factories import AlertFactory

_BACKFILL = importlib.import_module("core.migrations.0004_backfill_healpix_ipix")


@pytest.mark.django_db
def test_backfill_populates_ipix_and_leaves_reliability_null():
    coords = [(10.0, 20.0), (200.0, -40.0), (0.1, 89.9)]
    for ra, dec in coords:
        AlertFactory(ra_deg=ra, dec_deg=dec)
    # Simulate pre-migration state: existing rows have null read-model columns.
    Alert.objects.update(healpix_ipix=None, reliability=None)

    _BACKFILL.backfill_healpix_ipix(global_apps, None)

    for alert in Alert.objects.all():
        assert alert.healpix_ipix == radec_to_ipix(alert.ra_deg, alert.dec_deg)
        assert alert.reliability is None


@pytest.mark.django_db
def test_backfill_is_idempotent():
    AlertFactory(ra_deg=45.0, dec_deg=45.0)
    AlertFactory(ra_deg=300.0, dec_deg=-10.0)
    Alert.objects.update(healpix_ipix=None)

    _BACKFILL.backfill_healpix_ipix(global_apps, None)
    first = {a.pk: a.healpix_ipix for a in Alert.objects.all()}
    _BACKFILL.backfill_healpix_ipix(global_apps, None)
    second = {a.pk: a.healpix_ipix for a in Alert.objects.all()}

    assert first == second
    assert all(value is not None for value in second.values())


@pytest.mark.django_db
def test_reverse_is_noop():
    _BACKFILL.noop_reverse(global_apps, None)
