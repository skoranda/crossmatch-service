"""R12 / AE4: a catalog open/compute error surfaces (batch reverts to INGESTED)
instead of being swallowed into a silent zero-match. "No spatial overlap" and an
empty result stay normal skips (alert completes as MATCHED with no matches)."""
from unittest.mock import MagicMock

import pandas as pd
import pytest
from django.test import override_settings

import tasks.crossmatch as crossmatch_mod
from core.models import Alert, CatalogMatch, Notification
from tasks.crossmatch import crossmatch_batch
from tests.factories import AlertFactory

TEST_CATALOGS = [
    {
        "name": "test_cat",
        "hats_url": "x",
        "source_id_column": "source_id",
        "ra_column": "ra",
        "dec_column": "dec",
        "payload_columns": ["mag"],
    }
]


@pytest.fixture(autouse=True)
def _mock_lsdb(monkeypatch):
    monkeypatch.setattr(crossmatch_mod.lsdb, "from_dataframe", lambda *a, **k: MagicMock())


@pytest.mark.django_db
@override_settings(CROSSMATCH_CATALOGS=TEST_CATALOGS)
def test_catalog_open_error_fails_loud(monkeypatch):
    # Covers AE4. A raising catalog seam must not silently zero-match.
    def _boom(*a, **k):
        raise RuntimeError("HealpixDataset.__init__() got an unexpected keyword argument")

    monkeypatch.setattr(crossmatch_mod, "crossmatch_alerts", _boom)
    alert = AlertFactory(status=Alert.Status.QUEUED)

    with pytest.raises(Exception):
        crossmatch_batch([str(alert.uuid)])

    alert.refresh_from_db()
    assert alert.status == Alert.Status.INGESTED  # reverted, not silently MATCHED
    assert CatalogMatch.objects.filter(alert=alert).count() == 0
    assert Notification.objects.filter(alert=alert).count() == 0


@pytest.mark.django_db
@override_settings(CROSSMATCH_CATALOGS=TEST_CATALOGS)
def test_no_spatial_overlap_is_normal_skip(monkeypatch):
    def _no_overlap(*a, **k):
        raise RuntimeError("Catalogs do not overlap in the sky")

    monkeypatch.setattr(crossmatch_mod, "crossmatch_alerts", _no_overlap)
    alert = AlertFactory(status=Alert.Status.QUEUED)

    crossmatch_batch([str(alert.uuid)])

    alert.refresh_from_db()
    assert alert.status == Alert.Status.MATCHED  # normal completion, zero matches
    assert CatalogMatch.objects.filter(alert=alert).count() == 0


@pytest.mark.django_db
@override_settings(CROSSMATCH_CATALOGS=TEST_CATALOGS)
def test_empty_result_is_normal(monkeypatch):
    monkeypatch.setattr(crossmatch_mod, "crossmatch_alerts", lambda *a, **k: pd.DataFrame())
    alert = AlertFactory(status=Alert.Status.QUEUED)

    crossmatch_batch([str(alert.uuid)])

    alert.refresh_from_db()
    assert alert.status == Alert.Status.MATCHED
    assert CatalogMatch.objects.filter(alert=alert).count() == 0
