"""U4 / R1, R2, R4, R9: the recent-crossmatch HTTP view.

Parameter parsing, defaults, 400s on bad input, the clamp-not-reject behavior
for an oversized page_size, cursor round-tripping through two GETs, cursor/param
conflict -> 400, and unauthenticated access on the DEV config. Query correctness
is covered by test_recent_crossmatch_service; these tests exercise the HTTP
adapter end-to-end through the URLconf.
"""

from datetime import timedelta

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from tests.factories import AlertFactory, CatalogMatchFactory, set_ingest_time

URL = '/api/recent-crossmatches'


@pytest.mark.django_db
def test_no_params_returns_200_default_window_and_detail(client):
    now = timezone.now()
    alert = AlertFactory(event_time=now)
    CatalogMatchFactory(alert=alert)
    set_ingest_time(alert, now - timedelta(hours=1))

    resp = client.get(URL)

    assert resp.status_code == 200
    body = resp.json()
    assert body['detail'] == 'matches'
    assert body['time_field'] == 'ingest_time'
    assert body['count'] == 1
    assert 'matches' in body['objects'][0]


@pytest.mark.django_db
def test_reverse_matches_url():
    assert reverse('recent-crossmatches') == URL


@pytest.mark.django_db
def test_explicit_params_passed_through(client):
    now = timezone.now()
    alert = AlertFactory(event_time=now - timedelta(hours=2))
    CatalogMatchFactory(alert=alert)

    start = (now - timedelta(hours=6)).isoformat()
    end = now.isoformat()
    resp = client.get(
        URL,
        {'start': start, 'end': end, 'time_field': 'event_time', 'detail': 'ids'},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body['detail'] == 'ids'
    assert body['time_field'] == 'event_time'
    assert body['count'] == 1
    assert body['objects'][0] == {
        'diaObjectId': alert.lsst_diaObject_diaObjectId
    }


@pytest.mark.django_db
def test_invalid_detail_returns_400(client):
    resp = client.get(URL, {'detail': 'bogus'})
    assert resp.status_code == 400
    assert 'error' in resp.json()


@pytest.mark.django_db
def test_invalid_time_field_returns_400(client):
    resp = client.get(URL, {'time_field': 'created_at'})
    assert resp.status_code == 400
    assert 'error' in resp.json()


@pytest.mark.django_db
def test_unparseable_start_returns_400(client):
    resp = client.get(URL, {'start': 'not-a-timestamp'})
    assert resp.status_code == 400
    assert 'error' in resp.json()


@pytest.mark.django_db
def test_non_integer_page_size_returns_400(client):
    resp = client.get(URL, {'page_size': 'abc'})
    assert resp.status_code == 400


@pytest.mark.django_db
def test_zero_page_size_returns_400(client):
    resp = client.get(URL, {'page_size': '0'})
    assert resp.status_code == 400


@pytest.mark.django_db
def test_malformed_cursor_returns_400(client):
    resp = client.get(URL, {'cursor': 'not-a-real-cursor!!'})
    assert resp.status_code == 400
    assert 'error' in resp.json()


@pytest.mark.django_db
def test_window_span_over_max_returns_400(client):
    now = timezone.now()
    resp = client.get(
        URL,
        {'start': (now - timedelta(days=365)).isoformat(), 'end': now.isoformat()},
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_first_page_returns_cursor_and_page_size(client):
    """AE1: no cursor over a window with more than page_size objects -> a page
    plus next_cursor, with page_size echoed in the body."""
    now = timezone.now()
    for i in range(2):
        alert = AlertFactory(event_time=now)
        CatalogMatchFactory(alert=alert)
        set_ingest_time(alert, now - timedelta(hours=1) - timedelta(minutes=i))

    resp = client.get(URL, {'page_size': '1', 'detail': 'ids'})

    assert resp.status_code == 200
    body = resp.json()
    assert body['page_size'] == 1
    assert body['count'] == 1
    assert body['next_cursor'] is not None


@pytest.mark.django_db
def test_follow_cursor_across_two_gets_covers_set(client):
    """AE2: following next_cursor through the real URLconf yields disjoint pages
    that together cover the seeded set."""
    now = timezone.now()
    ids = []
    for i in range(3):
        alert = AlertFactory(event_time=now)
        CatalogMatchFactory(alert=alert)
        set_ingest_time(alert, now - timedelta(hours=1) - timedelta(minutes=i))
        ids.append(alert.lsst_diaObject_diaObjectId)

    seen = []
    params = {'page_size': '1', 'detail': 'ids'}
    for _ in range(10):
        body = client.get(URL, params).json()
        seen.extend(o['diaObjectId'] for o in body['objects'])
        if body['next_cursor'] is None:
            break
        params = {'page_size': '1', 'cursor': body['next_cursor']}

    assert sorted(seen) == sorted(ids)
    assert len(seen) == len(set(seen))


@pytest.mark.django_db
def test_cursor_conflict_returns_400(client):
    """AE5: a cursor plus a conflicting time_field -> 400 JSON error."""
    now = timezone.now()
    for i in range(2):
        alert = AlertFactory(event_time=now - timedelta(minutes=i))
        CatalogMatchFactory(alert=alert)

    first = client.get(
        URL, {'page_size': '1', 'detail': 'ids', 'time_field': 'event_time'}
    ).json()

    resp = client.get(
        URL, {'cursor': first['next_cursor'], 'time_field': 'ingest_time'}
    )
    assert resp.status_code == 400
    assert 'error' in resp.json()


@override_settings(RECENT_CROSSMATCH_MAX_PAGE_SIZE=1)
@pytest.mark.django_db
def test_oversized_page_size_is_clamped_not_rejected(client):
    now = timezone.now()
    for i in range(2):
        alert = AlertFactory(event_time=now)
        CatalogMatchFactory(alert=alert)
        set_ingest_time(alert, now - timedelta(hours=1) - timedelta(minutes=i))

    resp = client.get(URL, {'page_size': '100000', 'detail': 'ids'})

    assert resp.status_code == 200
    assert resp.json()['page_size'] == 1
    assert resp.json()['count'] == 1


@pytest.mark.django_db
def test_stray_limit_param_is_ignored(client):
    """The retired ``limit`` param no longer truncates the page."""
    now = timezone.now()
    for i in range(3):
        alert = AlertFactory(event_time=now)
        CatalogMatchFactory(alert=alert)
        set_ingest_time(alert, now - timedelta(hours=1) - timedelta(minutes=i))

    resp = client.get(URL, {'limit': '1', 'detail': 'ids'})

    assert resp.status_code == 200
    assert resp.json()['count'] == 3  # limit ignored; default page size covers all


@pytest.mark.django_db
def test_detail_absent_defaults_to_matches(client):
    resp = client.get(URL)
    assert resp.status_code == 200
    assert resp.json()['detail'] == 'matches'


@pytest.mark.django_db
def test_endpoint_responds_without_authentication(client):
    """R11: no login/permission decorator; DEV serves the endpoint unauthenticated
    (no redirect to a login page, no 401/403)."""
    resp = client.get(URL)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_non_get_method_rejected(client):
    resp = client.post(URL)
    assert resp.status_code == 405


def test_healthz_returns_ok(client):
    resp = client.get('/healthz')
    assert resp.status_code == 200
    assert resp.json() == {'status': 'ok'}
