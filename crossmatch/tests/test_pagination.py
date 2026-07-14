"""U2 / R8, R9, AE5: the opaque keyset cursor codec.

The cursor round-trips a keyset position ``(time_field_value, dia_object_id)``
plus the pinned query context (``start``/``end``/``time_field``/``detail``) through
an opaque, unsigned ``base64url(compact JSON)`` token. These tests pin the exact
contracts the service relies on: lossless round-trip at microsecond precision, a
URL-safe token, reject-on-conflict against explicit params, and ``InvalidQuery``
on any malformed input.
"""

from datetime import datetime, timezone

import pytest

from api.errors import InvalidQuery
from api.pagination import Cursor, decode_cursor, encode_cursor, ensure_no_conflict


def _cursor(**overrides) -> Cursor:
    base = dict(
        time_field_value=datetime(2026, 7, 14, 1, 5, 53, 123456, tzinfo=timezone.utc),
        dia_object_id=170591542700933237,
        start=datetime(2026, 7, 14, 1, 0, 0, tzinfo=timezone.utc),
        end=datetime(2026, 7, 14, 13, 0, 0, 654321, tzinfo=timezone.utc),
        time_field='event_time',
        detail='matches',
    )
    base.update(overrides)
    return Cursor(**base)


def test_round_trip_preserves_every_field_at_microsecond_precision():
    cursor = _cursor()
    assert decode_cursor(encode_cursor(cursor)) == cursor


def test_round_trip_preserves_full_int64_object_id():
    cursor = _cursor(dia_object_id=9_223_372_036_854_775_807)
    assert decode_cursor(encode_cursor(cursor)).dia_object_id == cursor.dia_object_id


def test_encoded_cursor_is_url_safe():
    token = encode_cursor(_cursor())
    assert '+' not in token and '/' not in token and '=' not in token


# --- ensure_no_conflict (KTD3, covers AE5) ---


def test_conflict_helper_accepts_matching_and_omitted_params():
    cursor = _cursor()
    # Omitted entirely.
    ensure_no_conflict(cursor)
    # All matching.
    ensure_no_conflict(
        cursor, start=cursor.start, end=cursor.end,
        time_field=cursor.time_field, detail=cursor.detail,
    )


@pytest.mark.parametrize('field', ['time_field', 'detail'])
def test_conflict_helper_rejects_conflicting_string_param(field):
    cursor = _cursor()
    with pytest.raises(InvalidQuery):
        ensure_no_conflict(cursor, **{field: 'ingest_time' if field == 'time_field' else 'full'})


def test_conflict_helper_rejects_conflicting_window():
    cursor = _cursor()
    other = datetime(2020, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(InvalidQuery):
        ensure_no_conflict(cursor, start=other)
    with pytest.raises(InvalidQuery):
        ensure_no_conflict(cursor, end=other)


# --- malformed input (all -> InvalidQuery) ---


def test_empty_cursor_raises():
    with pytest.raises(InvalidQuery):
        decode_cursor('')


def test_non_base64_cursor_raises():
    with pytest.raises(InvalidQuery):
        decode_cursor('not base64 !!!')


def test_oversized_cursor_rejected_before_decode():
    """An arbitrarily long cursor is rejected up front (unauthenticated endpoint
    must not base64/JSON-decode unbounded input)."""
    with pytest.raises(InvalidQuery):
        decode_cursor('A' * 5000)


def test_valid_base64_of_non_json_raises():
    import base64
    token = base64.urlsafe_b64encode(b'this is not json').decode('ascii').rstrip('=')
    with pytest.raises(InvalidQuery):
        decode_cursor(token)


def test_json_missing_required_key_raises():
    import base64
    import json
    # A well-formed token missing the object-id key.
    payload = {'t': '2026-07-14T01:05:53+00:00', 's': '2026-07-14T01:00:00+00:00',
               'e': '2026-07-14T13:00:00+00:00', 'f': 'event_time', 'd': 'matches'}
    raw = json.dumps(payload).encode('utf-8')
    token = base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')
    with pytest.raises(InvalidQuery):
        decode_cursor(token)


def test_json_unparseable_timestamp_raises():
    import base64
    import json
    payload = {'t': 'not-a-timestamp', 'i': 1, 's': '2026-07-14T01:00:00+00:00',
               'e': '2026-07-14T13:00:00+00:00', 'f': 'event_time', 'd': 'matches'}
    raw = json.dumps(payload).encode('utf-8')
    token = base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')
    with pytest.raises(InvalidQuery):
        decode_cursor(token)
