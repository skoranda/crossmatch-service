"""U1: a Celery soft time limit bounds crossmatch_batch runtime, and when it fires
(SoftTimeLimitExceeded) the batch reverts its alerts to INGESTED via the on-raise
path instead of leaving them stranded QUEUED — including when the exception lands
in the per-row build loop, whose generic `except` must not swallow it (KTD4). Also
covers the revert/re-run idempotency the recovery relies on (KTD7).

The Dask/LSDB path is mocked at its seams (lsdb.from_dataframe, crossmatch_alerts);
the soft limit is simulated by raising SoftTimeLimitExceeded from a seam, since the
real signal does not fire inside a fast synchronous unit test.
"""

from unittest.mock import MagicMock

import pandas as pd
import pytest
from celery.exceptions import SoftTimeLimitExceeded
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


def _match_df(alert):
    return pd.DataFrame(
        [
            {
                "lsst_diaObject_diaObjectId": alert.lsst_diaObject_diaObjectId,
                "source_id": "cat-1",
                "_dist_arcsec": 0.4,
                "ra": 180.0,
                "dec": -30.0,
                "mag": 18.2,
            }
        ]
    )


@pytest.mark.django_db
@override_settings(CROSSMATCH_CATALOGS=TEST_CATALOGS)
def test_soft_limit_during_compute_reverts(monkeypatch):
    # Covers AE2. The soft limit firing during the catalog read/compute raises
    # SoftTimeLimitExceeded; the batch reverts its alerts to INGESTED, publishes
    # nothing, and re-raises -- never leaving them stranded QUEUED.
    def _soft(*a, **k):
        raise SoftTimeLimitExceeded()

    monkeypatch.setattr(crossmatch_mod, "crossmatch_alerts", _soft)
    alert = AlertFactory(status=Alert.Status.QUEUED)

    with pytest.raises(SoftTimeLimitExceeded):
        crossmatch_batch([str(alert.uuid)])

    alert.refresh_from_db()
    assert alert.status == Alert.Status.INGESTED
    assert Notification.objects.filter(alert=alert).count() == 0
    assert CatalogMatch.objects.filter(alert=alert).count() == 0


@pytest.mark.django_db
@override_settings(CROSSMATCH_CATALOGS=TEST_CATALOGS)
def test_soft_limit_chained_from_transient_not_skipped(monkeypatch):
    # The soft limit can fire while a transient read error is being handled, which
    # implicitly chains it (SoftTimeLimitExceeded.__context__ = the transient exc).
    # The per-catalog handler classifies transient errors by walking that chain, so
    # it must match the soft limit by TYPE first and revert -- not skip the catalog.
    def _soft_chained(*a, **k):
        try:
            raise RuntimeError("ServerDisconnectedError: peer dropped")
        except RuntimeError:
            raise SoftTimeLimitExceeded()

    monkeypatch.setattr(crossmatch_mod, "crossmatch_alerts", _soft_chained)
    alert = AlertFactory(status=Alert.Status.QUEUED)

    with pytest.raises(SoftTimeLimitExceeded):
        crossmatch_batch([str(alert.uuid)])

    alert.refresh_from_db()
    assert alert.status == Alert.Status.INGESTED  # reverted, not skipped
    assert Notification.objects.filter(alert=alert).count() == 0


@pytest.mark.django_db
@override_settings(CROSSMATCH_CATALOGS=TEST_CATALOGS)
def test_soft_limit_during_row_build_not_swallowed(monkeypatch):
    # KTD4 guard: the soft limit can fire while a match row is being built, where
    # the per-row `except Exception: continue` would otherwise swallow it and let
    # the batch finish MATCHED. It must re-raise so the batch reverts instead.
    alert = AlertFactory(status=Alert.Status.QUEUED)
    monkeypatch.setattr(
        crossmatch_mod, "crossmatch_alerts", lambda *a, **k: _match_df(alert)
    )

    def _soft(*a, **k):
        raise SoftTimeLimitExceeded()

    monkeypatch.setattr(crossmatch_mod, "build_published_payload", _soft)

    with pytest.raises(SoftTimeLimitExceeded):
        crossmatch_batch([str(alert.uuid)])

    alert.refresh_from_db()
    assert alert.status == Alert.Status.INGESTED  # not swallowed; reverted
    assert Notification.objects.filter(alert=alert).count() == 0


@pytest.mark.django_db
@override_settings(CROSSMATCH_CATALOGS=TEST_CATALOGS)
def test_normal_batch_under_limit_completes(monkeypatch):
    # No false revert: a batch that finishes under the limit reaches MATCHED.
    alert = AlertFactory(status=Alert.Status.QUEUED)
    monkeypatch.setattr(
        crossmatch_mod, "crossmatch_alerts", lambda *a, **k: _match_df(alert)
    )

    crossmatch_batch([str(alert.uuid)])

    alert.refresh_from_db()
    assert alert.status == Alert.Status.MATCHED
    assert CatalogMatch.objects.filter(alert=alert).count() == 1


@pytest.mark.django_db
@override_settings(CROSSMATCH_CATALOGS=TEST_CATALOGS)
def test_revert_then_rerun_is_idempotent(monkeypatch):
    # KTD7 / OQ3. A batch that wrote CatalogMatch rows then reverted (finalization
    # failed, so it published nothing) is re-dispatched at the same match_version:
    # the CatalogMatch re-write is idempotent (unique_catalog_match + ignore_conflicts)
    # and Notifications are created once (run 1 never reached finalization).
    alert = AlertFactory(status=Alert.Status.QUEUED)
    monkeypatch.setattr(
        crossmatch_mod, "crossmatch_alerts", lambda *a, **k: _match_df(alert)
    )

    # Run 1: force finalization (step 4) to fail AFTER CatalogMatch was written.
    real_bulk = Notification.objects.bulk_create

    def _boom_notifications(*a, **k):
        raise RuntimeError("finalization failed")

    monkeypatch.setattr(Notification.objects, "bulk_create", _boom_notifications)

    with pytest.raises(RuntimeError):
        crossmatch_batch([str(alert.uuid)])

    alert.refresh_from_db()
    assert alert.status == Alert.Status.INGESTED  # reverted
    assert CatalogMatch.objects.filter(alert=alert).count() == 1  # written in-loop
    assert Notification.objects.filter(alert=alert).count() == 0  # never finalized

    # Run 2: re-dispatch; finalization works this time.
    monkeypatch.setattr(Notification.objects, "bulk_create", real_bulk)
    Alert.objects.filter(pk=alert.pk).update(status=Alert.Status.QUEUED)

    crossmatch_batch([str(alert.uuid)])

    alert.refresh_from_db()
    assert alert.status == Alert.Status.MATCHED
    assert CatalogMatch.objects.filter(alert=alert).count() == 1  # no duplicate
    assert Notification.objects.filter(alert=alert).count() == 1  # created once


def test_time_limits_below_stuck_threshold():
    # Ordering constraint (KTD5/KTD6): the recovery timer must never reclaim a live
    # batch, so the crossmatch_batch time limits must sit below the stuck threshold
    # (a live batch self-reverts at its soft limit before the timer fires), with a
    # margin over the soft limit for broker/pickup latency + clock skew. This pins
    # the shipped defaults so a future edit can't silently invert them.
    from django.conf import settings

    soft = crossmatch_batch.soft_time_limit
    hard = crossmatch_batch.time_limit
    stuck = settings.CROSSMATCH_BATCH_STUCK_SECONDS

    assert soft is not None and hard is not None
    assert soft < hard  # hard time limit is a SIGKILL backstop above soft
    assert hard < stuck  # a batch self-reverts (or is killed) before the timer reclaims
    assert stuck - soft >= 120  # margin for pickup latency + clock skew
