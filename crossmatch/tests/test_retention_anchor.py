"""notified_at is set at every terminal transition (U2 / KTD1).

Three terminal sites: the NOTIFIED transition (matched alerts), the no-match
crossmatch completion, and the invalid-coordinate early return. The LSDB/Dask path
is mocked at its two seams, following test_crossmatch_notify_ordering.py.
"""

import math
from unittest.mock import MagicMock

import pandas as pd
import pytest
from django.test import override_settings
from django.utils import timezone

import tasks.crossmatch as crossmatch_mod
from core.models import Alert, Notification
from notifier import dispatch as dispatch_module
from tasks.crossmatch import crossmatch_batch
from tasks.schedule import dispatch_notifications
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


def _send_ok(notifications):
    for n in notifications:
        n.state = Notification.State.SENT
        n.sent_at = timezone.now()
        n.save(update_fields=["state", "sent_at", "updated_at"])


@pytest.mark.django_db(transaction=True)
@override_settings(CROSSMATCH_CATALOGS=TEST_CATALOGS)
def test_matched_alert_notified_at_set_at_notified_transition(monkeypatch):
    alert = AlertFactory(status=Alert.Status.QUEUED)
    monkeypatch.setattr(
        crossmatch_mod.lsdb, "from_dataframe", lambda *a, **k: MagicMock()
    )
    result = pd.DataFrame(
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
    monkeypatch.setattr(crossmatch_mod, "crossmatch_alerts", lambda *a, **k: result)

    crossmatch_batch([str(alert.uuid)])
    alert.refresh_from_db()
    # MATCHED but not yet notified -> anchor stays NULL until the notify path runs.
    assert alert.status == Alert.Status.MATCHED
    assert alert.notified_at is None

    monkeypatch.setitem(dispatch_module.DESTINATION_HANDLERS, "hopskotch", _send_ok)
    dispatch_notifications()
    alert.refresh_from_db()
    assert alert.status == Alert.Status.NOTIFIED
    assert alert.notified_at is not None  # site 3


@pytest.mark.django_db(transaction=True)
@override_settings(CROSSMATCH_CATALOGS=TEST_CATALOGS)
def test_no_match_alert_notified_at_set_at_completion(monkeypatch):
    alert = AlertFactory(status=Alert.Status.QUEUED)
    monkeypatch.setattr(
        crossmatch_mod.lsdb, "from_dataframe", lambda *a, **k: MagicMock()
    )
    empty = pd.DataFrame(
        columns=["lsst_diaObject_diaObjectId", "source_id", "_dist_arcsec", "ra", "dec", "mag"]
    )
    monkeypatch.setattr(crossmatch_mod, "crossmatch_alerts", lambda *a, **k: empty)

    crossmatch_batch([str(alert.uuid)])
    alert.refresh_from_db()
    assert alert.status == Alert.Status.MATCHED
    assert Notification.objects.filter(alert=alert).count() == 0
    assert alert.notified_at is not None  # site 2 (no-match terminal)


@pytest.mark.django_db(transaction=True)
@override_settings(CROSSMATCH_CATALOGS=TEST_CATALOGS)
def test_invalid_coordinate_batch_notified_at_set_at_early_return(monkeypatch):
    alert = AlertFactory(status=Alert.Status.QUEUED, ra_deg=math.nan, dec_deg=math.nan)
    monkeypatch.setattr(
        crossmatch_mod.lsdb, "from_dataframe", lambda *a, **k: MagicMock()
    )

    crossmatch_batch([str(alert.uuid)])
    alert.refresh_from_db()
    assert alert.status == Alert.Status.MATCHED
    assert alert.notified_at is not None  # site 1 (invalid-coord early return)


@pytest.mark.django_db(transaction=True)
@override_settings(CROSSMATCH_CATALOGS=TEST_CATALOGS)
def test_mixed_batch_anchors_only_the_non_matched_subset(monkeypatch):
    # A heterogeneous batch: one matched, one valid-coord no-match, one invalid-coord.
    # Only the non-matched subset is terminal at step 4 and gets notified_at; the
    # matched alert must stay NULL (anchored later at NOTIFIED), never overwritten.
    matched = AlertFactory(status=Alert.Status.QUEUED)
    no_match = AlertFactory(status=Alert.Status.QUEUED)
    invalid = AlertFactory(
        status=Alert.Status.QUEUED, ra_deg=math.nan, dec_deg=math.nan
    )
    monkeypatch.setattr(
        crossmatch_mod.lsdb, "from_dataframe", lambda *a, **k: MagicMock()
    )
    result = pd.DataFrame(
        [
            {
                "lsst_diaObject_diaObjectId": matched.lsst_diaObject_diaObjectId,
                "source_id": "cat-1",
                "_dist_arcsec": 0.4,
                "ra": 180.0,
                "dec": -30.0,
                "mag": 18.2,
            }
        ]
    )
    monkeypatch.setattr(crossmatch_mod, "crossmatch_alerts", lambda *a, **k: result)

    crossmatch_batch([str(matched.uuid), str(no_match.uuid), str(invalid.uuid)])
    for a in (matched, no_match, invalid):
        a.refresh_from_db()
    assert matched.status == Alert.Status.MATCHED
    assert matched.notified_at is None  # matched alert not anchored at step 4
    assert no_match.notified_at is not None
    assert invalid.notified_at is not None
