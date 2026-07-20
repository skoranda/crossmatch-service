"""Hopskotch notification backend — publishes to SCiMMA Kafka via hop-client."""

from hop import Stream
from hop.auth import Auth
from django.conf import settings
from django.utils import timezone
from core.models import Notification
from core.log import get_logger
from core.metrics import NOTIFICATIONS_PUBLISHED

logger = get_logger(__name__)


def send_hopskotch_batch(notifications: list[Notification]) -> None:
    """Publish a batch of notifications to Hopskotch via hop-client.

    Opens one Kafka connection per batch for efficiency. hop/librdkafka
    ``produce`` is asynchronous: ``write()`` only enqueues a message, and the
    broker's per-message accept/reject (for example ``TOPIC_AUTHORIZATION_FAILED``)
    is reported later — via the delivery callback, when ``flush()`` runs. A
    notification is therefore marked ``SENT`` only once its delivery callback
    reports success, never at ``write()`` time, so a rejected batch is recorded
    ``FAILED`` (and retried) instead of being silently reported as delivered.

    Args:
        notifications: The pending ``Notification`` rows to publish. Each row's
            ``payload`` is written as one Kafka message.

    Returns:
        None. Each notification's ``state``, ``sent_at``, ``attempts`` and
        ``last_error`` are updated in place to reflect its delivery outcome.
    """
    url = f"{settings.HOPSKOTCH_BROKER_URL}/{settings.HOPSKOTCH_TOPIC}"
    if settings.HOPSKOTCH_USERNAME:
        auth = Auth(
            user=settings.HOPSKOTCH_USERNAME, password=settings.HOPSKOTCH_PASSWORD
        )
    else:
        auth = False
    stream = Stream(auth=auth)

    # Per-notification delivery outcome, keyed by pk. A key is present only once
    # that notification's delivery callback has fired: value ``None`` means
    # delivered, otherwise the failure reason. Absence after ``flush()`` means the
    # broker never confirmed the message, which we treat as a failure so it retries
    # rather than being silently dropped.
    delivery_error: dict[int, str | None] = {}

    def _make_callback(notif_id: int):
        def _on_delivery(kafka_error, msg=None) -> None:
            err = kafka_error
            if err is None and msg is not None:
                msg_err = msg.error()
                if msg_err is not None:
                    err = msg_err
            delivery_error[notif_id] = None if err is None else str(err)

        return _on_delivery

    connection_error: str | None = None
    try:
        with stream.open(url, "w") as producer:
            for notif in notifications:
                producer.write(
                    notif.payload, delivery_callback=_make_callback(notif.pk)
                )
            # Block until every delivery callback has fired, so delivery_error is
            # populated before we decide each notification's state.
            producer.flush()
    except Exception as err:
        # A connection- or flush-level failure not attributed to a single message
        # (broker unreachable, auth handshake, fatal producer error). Any
        # notification without its own delivery report falls back to this reason.
        connection_error = str(err)
        logger.error(
            "Failed to publish batch to Hopskotch broker",
            url=url,
            error=connection_error,
        )

    sent = 0
    failed = 0
    now = timezone.now()
    error_sample: str | None = None
    for notif in notifications:
        if notif.pk in delivery_error:
            reason = delivery_error[notif.pk]  # None == delivered
        elif connection_error is not None:
            reason = connection_error
        else:
            reason = "no delivery confirmation received"

        notif.attempts += 1
        if reason is None:
            notif.state = Notification.State.SENT
            notif.sent_at = now
            notif.last_error = None
            notif.save(
                update_fields=[
                    "state",
                    "sent_at",
                    "last_error",
                    "attempts",
                    "updated_at",
                ]
            )
            sent += 1
        else:
            notif.state = Notification.State.FAILED
            notif.last_error = reason[:500]
            notif.save(update_fields=["state", "last_error", "attempts", "updated_at"])
            failed += 1
            if error_sample is None:
                error_sample = reason

    if sent:
        NOTIFICATIONS_PUBLISHED.labels(result="success").inc(sent)
    if failed:
        NOTIFICATIONS_PUBLISHED.labels(result="failure").inc(failed)

    if failed:
        logger.warning(
            "Hopskotch batch published with failures",
            topic=settings.HOPSKOTCH_TOPIC,
            sent=sent,
            failed=failed,
            error_sample=error_sample,
        )
    else:
        logger.info(
            "Hopskotch batch published",
            topic=settings.HOPSKOTCH_TOPIC,
            sent=sent,
            failed=failed,
        )
