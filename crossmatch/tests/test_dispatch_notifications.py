"""R4 / AE1: dispatch_notifications advances MATCHED -> NOTIFIED iff all of an
alert's notifications are sent. Also guards the pk-vs-natural-key regression — the
transition must filter by lsst_diaObject_diaObjectId, not the uuid pk."""
import pytest
from django.utils import timezone

from core.models import Alert, Notification
from notifier import dispatch as dispatch_module
from tasks.schedule import dispatch_notifications
from tests.factories import AlertFactory, NotificationFactory


def _send_ok(notifications):
    for n in notifications:
        n.state = Notification.State.SENT
        n.sent_at = timezone.now()
        n.save(update_fields=["state", "sent_at", "updated_at"])


def _send_fail(notifications):
    for n in notifications:
        n.state = Notification.State.FAILED
        n.last_error = "boom"
        n.save(update_fields=["state", "last_error", "updated_at"])


@pytest.fixture
def ok_handler(monkeypatch):
    monkeypatch.setitem(dispatch_module.DESTINATION_HANDLERS, "hopskotch", _send_ok)


@pytest.fixture
def fail_handler(monkeypatch):
    monkeypatch.setitem(dispatch_module.DESTINATION_HANDLERS, "hopskotch", _send_fail)


@pytest.mark.django_db
def test_all_sent_advances_to_notified(ok_handler):
    # Covers AE1. Regression: a pk-based filter would match nothing and leave MATCHED.
    alert = AlertFactory(status=Alert.Status.MATCHED)
    NotificationFactory(alert=alert, state=Notification.State.PENDING)

    dispatch_notifications()

    alert.refresh_from_db()
    assert alert.status == Alert.Status.NOTIFIED


@pytest.mark.django_db
def test_unsent_notification_keeps_matched(fail_handler):
    # Covers AE1 (negative): a failed send leaves the alert at MATCHED.
    alert = AlertFactory(status=Alert.Status.MATCHED)
    NotificationFactory(alert=alert, state=Notification.State.PENDING)

    dispatch_notifications()

    alert.refresh_from_db()
    assert alert.status == Alert.Status.MATCHED


@pytest.mark.django_db
def test_multi_notification_all_sent_advances(ok_handler):
    alert = AlertFactory(status=Alert.Status.MATCHED)
    NotificationFactory(alert=alert, state=Notification.State.PENDING)
    NotificationFactory(alert=alert, state=Notification.State.PENDING)

    dispatch_notifications()

    alert.refresh_from_db()
    assert alert.status == Alert.Status.NOTIFIED
    assert alert.notification_set.filter(state=Notification.State.SENT).count() == 2
