"""Catalog-error behavior that stays fail-loud after the resilience change.

Transient read failures are now skipped best-effort (see
test_crossmatch_catalog_skip); this file pins the errors that must still NOT be
swallowed. A DETERMINISTIC error -- a bad/missing column (ValueError from
_get_catalog) or a dependency/version-skew mismatch -- is not transient, so it
surfaces and reverts the batch instead of silently dropping the catalog. "No
spatial overlap" and an empty result stay normal skips (alert completes MATCHED,
no matches)."""

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
    monkeypatch.setattr(
        crossmatch_mod.lsdb, "from_dataframe", lambda *a, **k: MagicMock()
    )


@pytest.mark.django_db
@override_settings(CROSSMATCH_CATALOGS=TEST_CATALOGS)
def test_deterministic_error_fails_loud(monkeypatch):
    # A deterministic error (here a bad/missing-column ValueError, the exact
    # shape _get_catalog raises up front) is NOT transient, so it must still fail
    # loud: the batch reverts to INGESTED rather than completing MATCHED with a
    # silently-dropped catalog. Resilience covers transient reads, not this.
    def _boom(*a, **k):
        raise ValueError(
            "test_cat: requested columns not found in catalog schema: ['mag']"
        )

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
    monkeypatch.setattr(
        crossmatch_mod, "crossmatch_alerts", lambda *a, **k: pd.DataFrame()
    )
    alert = AlertFactory(status=Alert.Status.QUEUED)

    crossmatch_batch([str(alert.uuid)])

    alert.refresh_from_db()
    assert alert.status == Alert.Status.MATCHED
    assert CatalogMatch.objects.filter(alert=alert).count() == 0
