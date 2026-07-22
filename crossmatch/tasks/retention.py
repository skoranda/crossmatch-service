"""Payload retention sweep.

Nulls the raw ``payload`` of terminal alerts and sent notifications once they are
older than the grace period, keeping the rows (their result lives in
``catalog_matches`` / ``core_notification``). See the payload-retention plan.

The sweep is bounded per run and idempotent, so Celery Beat can call it on a fixed
cadence without ever starving ingest/crossmatch/notify.
"""

from datetime import timedelta

from django.utils import timezone

from core.log import get_logger

logger = get_logger(__name__)


def sweep_payloads(grace_days: int, max_rows: int) -> dict:
    """Null payloads for terminal alerts/notifications older than the grace period.

    Alerts anchor on ``notified_at`` (set at every terminal transition — NOTIFIED,
    and crossmatch-completion for no-match alerts); notifications anchor on
    ``sent_at``. In-flight alerts (``notified_at`` NULL) and PENDING/FAILED
    notifications (``sent_at`` NULL) are excluded by the ``__lt`` comparison, so
    their payloads are retained regardless of age.

    Bounded to ``max_rows`` per model per run. Idempotent: only rows still carrying
    a payload are selected, so a re-run over already-cleared rows changes nothing.

    Args:
        grace_days: Clear a payload once its anchor timestamp is older than this
            many days.
        max_rows: Maximum rows to clear per model this run.

    Returns:
        ``{'alerts_cleared': int, 'notifications_cleared': int}``.
    """
    from core.models import Alert, Notification

    cutoff = timezone.now() - timedelta(days=grace_days)

    def _clear(model, anchor_field) -> int:
        # A sliced (LIMIT) queryset cannot be updated directly, so select the
        # capped pk set first, then update it. An empty pk set short-circuits to
        # zero rows with no SQL.
        pks = list(
            model.objects.filter(
                payload__isnull=False, **{f'{anchor_field}__lt': cutoff}
            ).values_list('pk', flat=True)[:max_rows]
        )
        return model.objects.filter(pk__in=pks).update(payload=None)

    alerts_cleared = _clear(Alert, 'notified_at')
    notifications_cleared = _clear(Notification, 'sent_at')

    if alerts_cleared or notifications_cleared:
        logger.info(
            'Retention sweep cleared payloads',
            alerts_cleared=alerts_cleared,
            notifications_cleared=notifications_cleared,
            grace_days=grace_days,
        )
    return {
        'alerts_cleared': alerts_cleared,
        'notifications_cleared': notifications_cleared,
    }
