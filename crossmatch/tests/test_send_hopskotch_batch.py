"""send_hopskotch_batch delivery accounting.

Regression: hop/librdkafka ``produce`` is asynchronous -- ``write()`` only
enqueues a message and the broker's accept/reject arrives later via the delivery
callback during ``flush()``. A notification must be marked SENT only on a
successful delivery report, never at ``write()`` time, so a rejected batch (e.g.
``TOPIC_AUTHORIZATION_FAILED``) is recorded FAILED and retried rather than
silently reported as delivered.
"""

import pytest

from core.models import Notification
from notifier import impl_hopskotch
from tests.factories import NotificationFactory


class _FakeMsg:
    def __init__(self, err):
        self._err = err

    def error(self):
        return self._err


class _FakeProducer:
    """Records writes; ``flush()`` fires each delivery callback with a preset outcome.

    ``outcomes`` is a list parallel to the writes: each entry is ``None`` (the
    message was delivered) or a non-None error object (delivery failed).
    """

    def __init__(self, outcomes):
        self._outcomes = outcomes
        self._callbacks = []

    def write(self, message, delivery_callback=None, **kwargs):
        self._callbacks.append(delivery_callback)

    def flush(self, *args, **kwargs):
        # Fire a delivery callback only for messages that got a report. Writes past
        # the end of ``outcomes`` model messages the broker never confirmed.
        for i, callback in enumerate(self._callbacks):
            if i < len(self._outcomes):
                callback(self._outcomes[i], _FakeMsg(None))
        return len(self._callbacks) - len(self._outcomes)


class _FakeStream:
    def __init__(self, producer=None, open_error=None):
        self._producer = producer
        self._open_error = open_error

    def open(self, url, mode):
        if self._open_error is not None:
            raise self._open_error
        producer = self._producer

        class _Ctx:
            def __enter__(self):
                return producer

            def __exit__(self, *exc):
                return False

        return _Ctx()


@pytest.fixture(autouse=True)
def _no_auth(settings):
    # Force the no-auth branch so the test never constructs a real hop Auth,
    # regardless of HOPSKOTCH_* env in the container running pytest.
    settings.HOPSKOTCH_USERNAME = ""
    settings.HOPSKOTCH_BROKER_URL = "kafka://broker.test"
    settings.HOPSKOTCH_TOPIC = "test-topic"


def _patch_stream(monkeypatch, producer=None, open_error=None):
    monkeypatch.setattr(
        impl_hopskotch, "Stream", lambda *a, **k: _FakeStream(producer, open_error)
    )


@pytest.mark.django_db
def test_delivered_messages_marked_sent(monkeypatch):
    notifs = [NotificationFactory(state=Notification.State.PENDING) for _ in range(3)]
    _patch_stream(monkeypatch, _FakeProducer(outcomes=[None, None, None]))

    impl_hopskotch.send_hopskotch_batch(notifs)

    for n in notifs:
        n.refresh_from_db()
        assert n.state == Notification.State.SENT
        assert n.sent_at is not None
        assert n.last_error is None
        assert n.attempts == 1


@pytest.mark.django_db
def test_async_delivery_failure_marks_failed_not_sent(monkeypatch):
    # THE regression: write() returns (buffered) but the delivery callback reports
    # an error at flush(). Pre-fix this batch was marked sent=N failed=0.
    notifs = [NotificationFactory(state=Notification.State.PENDING) for _ in range(2)]
    _patch_stream(
        monkeypatch,
        _FakeProducer(
            outcomes=["TOPIC_AUTHORIZATION_FAILED", "TOPIC_AUTHORIZATION_FAILED"]
        ),
    )

    impl_hopskotch.send_hopskotch_batch(notifs)

    for n in notifs:
        n.refresh_from_db()
        assert n.state == Notification.State.FAILED
        assert n.sent_at is None
        assert "TOPIC_AUTHORIZATION_FAILED" in n.last_error
        assert n.attempts == 1


@pytest.mark.django_db
def test_mixed_outcomes_recorded_per_message(monkeypatch):
    ok = NotificationFactory(state=Notification.State.PENDING)
    bad = NotificationFactory(state=Notification.State.PENDING)
    _patch_stream(monkeypatch, _FakeProducer(outcomes=[None, "broker down"]))

    impl_hopskotch.send_hopskotch_batch([ok, bad])

    ok.refresh_from_db()
    bad.refresh_from_db()
    assert ok.state == Notification.State.SENT
    assert ok.sent_at is not None
    assert bad.state == Notification.State.FAILED
    assert bad.sent_at is None
    assert "broker down" in bad.last_error


@pytest.mark.django_db
def test_connection_error_marks_all_failed(monkeypatch):
    # stream.open() raises before any write -> every notification FAILED, none SENT.
    notifs = [NotificationFactory(state=Notification.State.PENDING) for _ in range(2)]
    _patch_stream(monkeypatch, open_error=RuntimeError("broker unreachable"))

    impl_hopskotch.send_hopskotch_batch(notifs)

    for n in notifs:
        n.refresh_from_db()
        assert n.state == Notification.State.FAILED
        assert n.sent_at is None
        assert "broker unreachable" in n.last_error


@pytest.mark.django_db
def test_missing_delivery_report_treated_as_failure(monkeypatch):
    # flush() that fires no callback for a message (no confirmation) must not be
    # counted as sent -- fail-safe so the message is retried, not lost.
    notif = NotificationFactory(state=Notification.State.PENDING)
    _patch_stream(monkeypatch, _FakeProducer(outcomes=[]))  # flush() fires nothing

    impl_hopskotch.send_hopskotch_batch([notif])

    notif.refresh_from_db()
    assert notif.state == Notification.State.FAILED
    assert notif.sent_at is None
