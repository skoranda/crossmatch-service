"""U2 / AE1-AE5: the recent-crossmatch query/service layer.

Covers the window filter on both timestamp fields, matches-only inner join,
grouping by object, the four detail levels, current-match_version dedup, and the
hard server-side object cap. ``ingest_time`` is ``auto_now_add`` so it cannot be
set at construction; tests that pin it use an explicit ``.update()`` after the
factory builds the row (mirroring how production stamps it on ingest).
"""

from datetime import timedelta

import pytest
from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from api.service import InvalidQuery, recent_crossmatches
from tests.factories import AlertFactory, CatalogMatchFactory, set_ingest_time


@pytest.mark.django_db
def test_matches_only_excludes_objects_without_matches():
    """AE2: an alert in the window but with no CatalogMatch is not returned."""
    now = timezone.now()
    matched = AlertFactory(event_time=now)
    CatalogMatchFactory(alert=matched)
    AlertFactory(event_time=now)  # no match -> excluded

    result = recent_crossmatches(time_field='event_time', detail='ids')

    returned = {o['diaObjectId'] for o in result['objects']}
    assert returned == {matched.lsst_diaObject_diaObjectId}
    assert result['count'] == 1


@pytest.mark.django_db
def test_window_excludes_alerts_outside_span_event_time():
    """AE1: only alerts whose event_time falls in [start, end) are returned."""
    now = timezone.now()
    inside = AlertFactory(event_time=now - timedelta(hours=2))
    CatalogMatchFactory(alert=inside)
    outside = AlertFactory(event_time=now - timedelta(hours=30))
    CatalogMatchFactory(alert=outside)

    result = recent_crossmatches(
        start=now - timedelta(hours=12), end=now, time_field='event_time',
        detail='ids',
    )

    returned = {o['diaObjectId'] for o in result['objects']}
    assert returned == {inside.lsst_diaObject_diaObjectId}


@pytest.mark.django_db
def test_window_filters_on_ingest_time_by_default():
    """AE1: the default time_field is ingest_time, independent of event_time."""
    now = timezone.now()
    # event_time is old, but ingest_time is recent -> inside the default window.
    recent_ingest = AlertFactory(event_time=now - timedelta(days=10))
    CatalogMatchFactory(alert=recent_ingest)
    set_ingest_time(recent_ingest, now - timedelta(hours=1))

    # event_time is recent, but ingest_time is old -> outside the window.
    old_ingest = AlertFactory(event_time=now)
    CatalogMatchFactory(alert=old_ingest)
    set_ingest_time(old_ingest, now - timedelta(days=5))

    result = recent_crossmatches(detail='ids')  # ingest_time default, 12h

    returned = {o['diaObjectId'] for o in result['objects']}
    assert returned == {recent_ingest.lsst_diaObject_diaObjectId}
    assert result['time_field'] == 'ingest_time'


@pytest.mark.django_db
def test_detail_ids_returns_only_object_ids():
    now = timezone.now()
    alert = AlertFactory(event_time=now)
    CatalogMatchFactory(alert=alert)

    result = recent_crossmatches(time_field='event_time', detail='ids')

    obj = result['objects'][0]
    assert obj == {'diaObjectId': alert.lsst_diaObject_diaObjectId}
    assert 'ra' not in obj and 'matches' not in obj


@pytest.mark.django_db
def test_detail_position_adds_object_coordinates():
    """AE3: position level adds the alert object's ra/dec (not source coords)."""
    now = timezone.now()
    alert = AlertFactory(event_time=now, ra_deg=12.5, dec_deg=-45.0)
    CatalogMatchFactory(alert=alert, source_ra_deg=99.0, source_dec_deg=99.0)

    result = recent_crossmatches(time_field='event_time', detail='position')

    obj = result['objects'][0]
    assert obj['ra'] == 12.5
    assert obj['dec'] == -45.0
    assert 'matches' not in obj


@pytest.mark.django_db
def test_detail_matches_lists_catalog_source_and_separation():
    """AE4: matches level lists catalog_name, catalog_source_id, separation."""
    now = timezone.now()
    alert = AlertFactory(event_time=now)
    CatalogMatchFactory(
        alert=alert, catalog_name='gaia_dr3', catalog_source_id='42',
        match_distance_arcsec=0.75,
    )

    result = recent_crossmatches(time_field='event_time', detail='matches')

    matches = result['objects'][0]['matches']
    assert len(matches) == 1
    assert matches[0] == {
        'catalog_name': 'gaia_dr3',
        'catalog_source_id': '42',
        'separation_arcsec': 0.75,
    }


@pytest.mark.django_db
def test_detail_full_reconstructs_published_payload():
    """AE5: full level reconstructs the published payload via the shared builder;
    ra/dec are the catalog source coords, not the object position."""
    now = timezone.now()
    alert = AlertFactory(event_time=now, ra_deg=1.0, dec_deg=2.0)
    CatalogMatchFactory(
        alert=alert, catalog_name='gaia_dr3', catalog_source_id='42',
        match_distance_arcsec=0.75, source_ra_deg=1.11, source_dec_deg=2.22,
        catalog_payload={'phot_g_mean_mag': 18.3},
    )

    result = recent_crossmatches(time_field='event_time', detail='full')

    match = result['objects'][0]['matches'][0]
    assert match == {
        'diaObjectId': alert.lsst_diaObject_diaObjectId,
        'ra': 1.11,
        'dec': 2.22,
        'catalog_name': 'gaia_dr3',
        'catalog_source_id': '42',
        'separation_arcsec': 0.75,
        'catalog_payload': {'phot_g_mean_mag': 18.3},
    }


@pytest.mark.django_db
def test_multiple_catalogs_group_under_one_object():
    now = timezone.now()
    alert = AlertFactory(event_time=now)
    CatalogMatchFactory(alert=alert, catalog_name='gaia_dr3', catalog_source_id='1')
    CatalogMatchFactory(alert=alert, catalog_name='des_y6_gold', catalog_source_id='2')

    result = recent_crossmatches(time_field='event_time', detail='matches')

    assert result['count'] == 1
    catalogs = {m['catalog_name'] for m in result['objects'][0]['matches']}
    assert catalogs == {'gaia_dr3', 'des_y6_gold'}


@pytest.mark.django_db
def test_only_current_match_version_is_returned():
    """A re-matched (object, catalog, source) surfaces once, at the highest
    match_version, not once per version."""
    now = timezone.now()
    alert = AlertFactory(event_time=now)
    CatalogMatchFactory(
        alert=alert, catalog_name='gaia_dr3', catalog_source_id='7',
        match_distance_arcsec=0.9, match_version=1,
    )
    CatalogMatchFactory(
        alert=alert, catalog_name='gaia_dr3', catalog_source_id='7',
        match_distance_arcsec=0.4, match_version=2,
    )

    result = recent_crossmatches(time_field='event_time', detail='matches')

    matches = result['objects'][0]['matches']
    assert len(matches) == 1
    assert matches[0]['separation_arcsec'] == 0.4  # the current version


@pytest.mark.django_db
def test_empty_window_returns_no_objects():
    result = recent_crossmatches(time_field='event_time', detail='matches')
    assert result['count'] == 0
    assert result['objects'] == []


@pytest.mark.django_db
def test_limit_clamps_to_max_objects():
    """A caller limit above the hard ceiling is clamped down to MAX_OBJECTS."""
    now = timezone.now()
    for _ in range(3):
        alert = AlertFactory(event_time=now)
        CatalogMatchFactory(alert=alert)

    result = recent_crossmatches(
        time_field='event_time', detail='ids', limit=settings.RECENT_CROSSMATCH_MAX_OBJECTS + 1000,
    )

    assert result["count"] <= settings.RECENT_CROSSMATCH_MAX_OBJECTS


@pytest.mark.django_db
def test_limit_narrows_object_count():
    now = timezone.now()
    for _ in range(3):
        alert = AlertFactory(event_time=now)
        CatalogMatchFactory(alert=alert)

    result = recent_crossmatches(time_field='event_time', detail='ids', limit=2)

    assert result['count'] == 2


@pytest.mark.django_db
def test_invalid_detail_raises():
    with pytest.raises(InvalidQuery):
        recent_crossmatches(detail='everything')


@pytest.mark.django_db
def test_invalid_time_field_raises():
    with pytest.raises(InvalidQuery):
        recent_crossmatches(time_field='created_at')


@pytest.mark.django_db
def test_non_positive_limit_raises():
    with pytest.raises(InvalidQuery):
        recent_crossmatches(limit=0)


@pytest.mark.django_db
def test_end_before_start_raises():
    now = timezone.now()
    with pytest.raises(InvalidQuery):
        recent_crossmatches(start=now, end=now - timedelta(hours=1))


@pytest.mark.django_db
def test_window_span_over_max_raises():
    now = timezone.now()
    with pytest.raises(InvalidQuery):
        recent_crossmatches(start=now - timedelta(days=365), end=now)


@pytest.mark.django_db
def test_full_detail_skips_row_with_null_source_coords():
    """A stored match with null source coords must not 500 the whole full
    response: the unbuildable row is skipped, the valid one survives."""
    now = timezone.now()
    alert = AlertFactory(event_time=now)
    CatalogMatchFactory(
        alert=alert, catalog_name='gaia_dr3', catalog_source_id='good',
        source_ra_deg=1.0, source_dec_deg=2.0,
    )
    CatalogMatchFactory(
        alert=alert, catalog_name='gaia_dr3', catalog_source_id='bad',
        source_ra_deg=None, source_dec_deg=None,
    )

    result = recent_crossmatches(time_field='event_time', detail='full')

    matches = result['objects'][0]['matches']
    assert [m['catalog_source_id'] for m in matches] == ['good']


@override_settings(RECENT_CROSSMATCH_MAX_OBJECTS=2)
@pytest.mark.django_db
def test_ceiling_read_live_from_settings():
    """The object ceiling is read live from settings (override_settings works
    because the value is not cached at import)."""
    now = timezone.now()
    for _ in range(3):
        alert = AlertFactory(event_time=now)
        CatalogMatchFactory(alert=alert)

    result = recent_crossmatches(time_field='event_time', detail='ids')

    assert result['count'] == 2
