"""R5 / AE2: notifications and the MATCHED transition commit atomically, so a
single-match alert reaches NOTIFIED even though the dispatcher and the batch run
as separate tasks. Run under real commit semantics (transaction=True) — the
default rollback would collapse the commit boundary this guards.

The Dask/LSDB path is mocked at its two seams (lsdb.from_dataframe and
crossmatch_alerts); a one-row result drives one match + one notification.
"""
from unittest.mock import MagicMock

import pandas as pd
import pytest
from django.test import override_settings
from django.utils import timezone

import tasks.crossmatch as crossmatch_mod
from core.models import Alert, CatalogMatch, Notification
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
def test_single_match_alert_commits_atomically_and_reaches_notified(monkeypatch):
    alert = AlertFactory(status=Alert.Status.QUEUED)
    monkeypatch.setattr(crossmatch_mod.lsdb, "from_dataframe", lambda *a, **k: MagicMock())
    result = pd.DataFrame(
        [
            {
                "lsst_diaObject_diaObjectId": alert.lsst_diaObject_diaObjectId,
                "source_id": "cat-123",
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
    assert alert.status == Alert.Status.MATCHED
    assert CatalogMatch.objects.filter(alert=alert).count() == 1
    assert Notification.objects.filter(alert=alert, state=Notification.State.PENDING).count() == 1
    # R5 invariant: a notification is never committed while its alert is still QUEUED.
    assert Notification.objects.filter(alert__status=Alert.Status.QUEUED).count() == 0

    # Covers AE2: the single-match alert advances to NOTIFIED via the dispatcher.
    monkeypatch.setitem(dispatch_module.DESTINATION_HANDLERS, "hopskotch", _send_ok)
    dispatch_notifications()
    alert.refresh_from_db()
    assert alert.status == Alert.Status.NOTIFIED
