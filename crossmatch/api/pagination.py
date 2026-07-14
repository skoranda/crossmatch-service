"""Opaque keyset cursor codec for the recent-crossmatch API.

A page's ``next_cursor`` names the last row of that page as a keyset position
``(time_field_value, dia_object_id)`` and pins the query context the cursor was
issued for (``start``/``end``/``time_field``/``detail``). The service resumes the
next page strictly after that position (see ``api/service.py``).

The token is ``base64url(compact JSON)`` and **unsigned**: it encodes only public
query parameters and a public keyset position, so a tampered cursor yields at
most a different *valid* public query the client could have issued directly.
There is no trust boundary to protect here (the endpoint is unauthenticated), but
the service still routes the decoded ``time_field``/``detail``/window through the
same allowlist and window-span validation as directly-supplied params before
using them, so a decoded value never reaches the ORM unchecked.

Timestamps round-trip as full-precision ISO-8601 so the ``=`` arm of the keyset
predicate (``time_field == t0``) holds exactly against the ``timestamptz``
microsecond resolution stored in Postgres.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime

from django.utils.dateparse import parse_datetime

from api.errors import InvalidQuery

# Compact JSON keys keep the token short. The wire shape is an implementation
# detail; clients treat the whole cursor as opaque.
_KEY_TIME_VALUE = 't'
_KEY_OBJECT_ID = 'i'
_KEY_START = 's'
_KEY_END = 'e'
_KEY_TIME_FIELD = 'f'
_KEY_DETAIL = 'd'


@dataclass(frozen=True)
class Cursor:
    """A decoded keyset cursor: a position plus the pinned query context."""

    time_field_value: datetime
    dia_object_id: int
    start: datetime
    end: datetime
    time_field: str
    detail: str


def encode_cursor(cursor: Cursor) -> str:
    """Serialize a :class:`Cursor` to an opaque URL-safe token.

    Args:
        cursor: The keyset position and pinned query context to encode.

    Returns:
        A ``base64url``-encoded compact-JSON string with no ``=`` padding, safe to
        pass as a bare query-string value.
    """
    payload = {
        _KEY_TIME_VALUE: cursor.time_field_value.isoformat(),
        _KEY_OBJECT_ID: cursor.dia_object_id,
        _KEY_START: cursor.start.isoformat(),
        _KEY_END: cursor.end.isoformat(),
        _KEY_TIME_FIELD: cursor.time_field,
        _KEY_DETAIL: cursor.detail,
    }
    raw = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def decode_cursor(raw: str) -> Cursor:
    """Parse an opaque token back into a :class:`Cursor`.

    Args:
        raw: The token produced by :func:`encode_cursor`.

    Returns:
        The decoded cursor.

    Raises:
        InvalidQuery: If the token is empty, not valid base64url, not JSON, is
            missing a required key, or carries an unparseable/ill-typed value.
    """
    if not raw:
        raise InvalidQuery('cursor must not be empty')
    try:
        padded = raw + '=' * (-len(raw) % 4)
        data = base64.urlsafe_b64decode(padded.encode('ascii'))
        payload = json.loads(data)
    except (ValueError, TypeError) as exc:
        raise InvalidQuery(f'cursor is not a valid token: {raw!r}') from exc

    if not isinstance(payload, dict):
        raise InvalidQuery('cursor is not a valid token')

    try:
        time_value = payload[_KEY_TIME_VALUE]
        object_id = payload[_KEY_OBJECT_ID]
        start = payload[_KEY_START]
        end = payload[_KEY_END]
        time_field = payload[_KEY_TIME_FIELD]
        detail = payload[_KEY_DETAIL]
    except (KeyError, TypeError) as exc:
        raise InvalidQuery('cursor is missing a required field') from exc

    if not isinstance(object_id, int) or isinstance(object_id, bool):
        raise InvalidQuery('cursor object id must be an integer')
    if not isinstance(time_field, str) or not isinstance(detail, str):
        raise InvalidQuery('cursor time_field/detail must be strings')

    return Cursor(
        time_field_value=_parse_dt(time_value),
        dia_object_id=object_id,
        start=_parse_dt(start),
        end=_parse_dt(end),
        time_field=time_field,
        detail=detail,
    )


def ensure_no_conflict(
    cursor: Cursor,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    time_field: str | None = None,
    detail: str | None = None,
) -> None:
    """Reject an explicit param that conflicts with the cursor's pinned context.

    The cursor is authoritative for ``{start, end, time_field, detail}`` (KTD3):
    a caller may omit them (the service derives them from the cursor) or repeat
    the matching value, but supplying a *different* value means the query drifted
    mid-iteration and is an error. ``page_size`` is intentionally not pinned --
    it is presentation, not result-set identity, and may vary per page.

    Raises:
        InvalidQuery: If any supplied param differs from the cursor's value.
    """
    if start is not None and start != cursor.start:
        raise InvalidQuery("start conflicts with the cursor's pinned window")
    if end is not None and end != cursor.end:
        raise InvalidQuery("end conflicts with the cursor's pinned window")
    if time_field is not None and time_field != cursor.time_field:
        raise InvalidQuery("time_field conflicts with the cursor's pinned context")
    if detail is not None and detail != cursor.detail:
        raise InvalidQuery("detail conflicts with the cursor's pinned context")


def _parse_dt(value: object) -> datetime:
    """Parse an ISO-8601 timestamp string from a cursor payload.

    Raises:
        InvalidQuery: If ``value`` is not a string parseable as an ISO-8601
            datetime.
    """
    if not isinstance(value, str):
        raise InvalidQuery('cursor timestamp must be a string')
    parsed = parse_datetime(value)
    if parsed is None:
        raise InvalidQuery(f'cursor timestamp is not valid ISO-8601: {value!r}')
    return parsed
