"""Read-model query layer for the recent-crossmatch API.

Returns the catalog crossmatches for objects that had an alert in a time
window, grouped by object, at a caller-selected detail level. This module is
the reusable seam other scientist-facing endpoints (object lookup, ranked
transients, cone search) and a future Python client can share; the HTTP view in
``api/views.py`` is a thin adapter over ``recent_crossmatches``.

The query is index-backed on the selected timestamp (``ingest_time`` default,
``event_time`` optional) and semi-joins ``CatalogMatch`` so objects with no
match are excluded (matches-only). The ``full`` detail level reconstructs the
exact published Hopskotch payload via the shared ``build_published_payload``
builder, so it cannot drift from what the crossmatch pipeline publishes.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.db.models import Exists, OuterRef
from django.utils import timezone

from core.log import get_logger
from core.models import Alert, CatalogMatch
from matching.payload import build_published_payload

# InvalidQuery is defined in api.errors so the cursor codec (api.pagination) can
# raise it without a circular import; re-exported here for existing importers.
from api.errors import InvalidQuery

logger = get_logger(__name__)

DETAIL_LEVELS = ('ids', 'position', 'matches', 'full')
TIME_FIELDS = ('ingest_time', 'event_time')
DEFAULT_DETAIL = 'matches'
DEFAULT_TIME_FIELD = 'ingest_time'
DEFAULT_WINDOW_HOURS = 12

__all__ = ['InvalidQuery', 'recent_crossmatches']


def recent_crossmatches(
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    time_field: str = DEFAULT_TIME_FIELD,
    detail: str = DEFAULT_DETAIL,
    limit: int | None = None,
) -> dict[str, Any]:
    """Return recent crossmatches grouped by object.

    Args:
        start: Window start (aware datetime). Defaults to ``end`` minus 12h.
        end: Window end (aware datetime). Defaults to now.
        time_field: Which alert timestamp the window filters on — ``ingest_time``
            (default, arrival time) or ``event_time`` (observation time).
        detail: Payload detail level — ``ids`` | ``position`` | ``matches`` |
            ``full`` (cumulative).
        limit: Optional caller cap on the number of objects; clamped to the hard
            server-side ceiling. Must be positive when given.

    Returns:
        A JSON-native dict with the resolved query metadata and an ``objects``
        list, one entry per ``diaObjectId`` (matches-only).

    Raises:
        InvalidQuery: On an unknown ``detail``/``time_field``, a non-positive
            ``limit``, an ``end`` before ``start``, or a window span beyond the
            configured maximum.
    """
    if detail not in DETAIL_LEVELS:
        raise InvalidQuery(
            f"detail must be one of {DETAIL_LEVELS}, got {detail!r}"
        )
    if time_field not in TIME_FIELDS:
        raise InvalidQuery(
            f"time_field must be one of {TIME_FIELDS}, got {time_field!r}"
        )
    if limit is not None and limit <= 0:
        raise InvalidQuery("limit must be a positive integer")

    # Hard server-side ceilings, read live (matching the repo convention of
    # reading settings at call time, so @override_settings works in tests). The
    # endpoint is unauthenticated on DEV with rate limiting deferred, so these
    # bound the work one request can cause (KTD7): a caller ``limit`` only
    # narrows below the object ceiling, and a window span beyond the hour
    # ceiling is rejected.
    max_objects = int(settings.RECENT_CROSSMATCH_MAX_OBJECTS)
    max_window_hours = int(settings.RECENT_CROSSMATCH_MAX_WINDOW_HOURS)

    end = end or timezone.now()
    start = start or (end - timedelta(hours=DEFAULT_WINDOW_HOURS))
    if end < start:
        raise InvalidQuery("end must not be earlier than start")
    if (end - start) > timedelta(hours=max_window_hours):
        raise InvalidQuery(
            f"window span exceeds the maximum of {max_window_hours} hours"
        )

    cap = max_objects if limit is None else min(limit, max_objects)

    window = {f'{time_field}__gte': start, f'{time_field}__lt': end}

    # Objects (one Alert per diaObjectId, since diaObjectId is unique) that have
    # at least one match, in the window, newest first, capped. An Exists()
    # semi-join expresses "has a match" without the inner-join fan-out (one row
    # per match) that would otherwise need a GROUP BY to collapse, so the
    # planner can serve the ORDER BY + LIMIT straight off the timestamp index.
    # ra/dec are pulled in the same query (functionally dependent on the unique
    # object id) so position/matches/full need no second round trip. The
    # diaObjectId tiebreaker makes the cap truncation deterministic when several
    # objects share a timestamp at the cap boundary.
    has_match = CatalogMatch.objects.filter(
        alert_id=OuterRef('lsst_diaObject_diaObjectId')
    )
    object_rows = list(
        Alert.objects.filter(**window)
        .filter(Exists(has_match))
        .order_by(f'-{time_field}', 'lsst_diaObject_diaObjectId')
        .values('lsst_diaObject_diaObjectId', 'ra_deg', 'dec_deg')[:cap]
    )

    objects = [{'diaObjectId': int(r['lsst_diaObject_diaObjectId'])} for r in object_rows]
    if detail == 'ids' or not object_rows:
        return _envelope(start, end, time_field, detail, objects)

    for obj, row in zip(objects, object_rows):
        ra, dec = row['ra_deg'], row['dec_deg']
        obj['ra'] = float(ra) if ra is not None else None
        obj['dec'] = float(dec) if dec is not None else None

    if detail == 'position':
        return _envelope(start, end, time_field, detail, objects)

    object_ids = [obj['diaObjectId'] for obj in objects]
    matches_by_object = _load_matches(object_ids, detail)
    for obj in objects:
        obj['matches'] = matches_by_object.get(obj['diaObjectId'], [])

    return _envelope(start, end, time_field, detail, objects)


def _load_matches(object_ids, detail):
    """Return {diaObjectId: [match_entry, ...]} for the given objects.

    Postgres ``DISTINCT ON (object, catalog, source)`` combined with an
    ``ORDER BY ... -match_version`` keeps only the current match version per
    match, so a re-matched object does not surface duplicate rows across
    versions and older versions are never fetched. At the ``full`` level each
    entry is the reconstructed published payload; at ``matches`` each entry is
    the catalog/source/separation summary (and the heavier ``catalog_payload``
    column is not loaded).

    Each row is built defensively: an unexpected value in one stored row (e.g. a
    null/non-finite source coordinate on a ``full`` build) is logged and skipped
    without 500-ing the whole response, mirroring the per-row guard on the write
    path in ``tasks/crossmatch.py``.
    """
    rows = (
        CatalogMatch.objects.filter(alert_id__in=object_ids)
        .order_by('alert_id', 'catalog_name', 'catalog_source_id', '-match_version')
        .distinct('alert_id', 'catalog_name', 'catalog_source_id')
    )
    if detail != 'full':
        rows = rows.only(
            'alert_id', 'catalog_name', 'catalog_source_id', 'match_distance_arcsec'
        )

    result: dict[int, list[dict[str, Any]]] = {}
    for cm in rows:
        try:
            oid = int(cm.alert_id)
            if detail == 'full':
                entry = build_published_payload(
                    cm.alert_id,
                    cm.source_ra_deg,
                    cm.source_dec_deg,
                    cm.catalog_name,
                    cm.catalog_source_id,
                    cm.match_distance_arcsec,
                    cm.catalog_payload,
                )
            else:  # 'matches'
                entry = {
                    'catalog_name': cm.catalog_name,
                    'catalog_source_id': cm.catalog_source_id,
                    'separation_arcsec': float(cm.match_distance_arcsec),
                }
        except Exception:
            logger.exception('Skipping unbuildable match row',
                             catalog=getattr(cm, 'catalog_name', None))
            continue
        result.setdefault(oid, []).append(entry)
    return result


def _envelope(
    start: datetime,
    end: datetime,
    time_field: str,
    detail: str,
    objects: list[dict[str, Any]],
) -> dict[str, Any]:
    """Wrap the projected objects with the resolved query metadata."""
    return {
        'window': {'start': start.isoformat(), 'end': end.isoformat()},
        'time_field': time_field,
        'detail': detail,
        'count': len(objects),
        'objects': objects,
    }
