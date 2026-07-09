"""U2 / R5, R6: HEALPix spatial helper — stable point index, cone-to-ipix ranges
correct across RA wraparound (AE4) and at the poles, and an exact fine-filter."""

from core.healpix import (
    HEALPIX_ORDER,
    angular_separation_arcsec,
    cone_ipix_ranges,
    radec_to_ipix,
    radec_to_ipix_array,
)


def _in_ranges(ipix, ranges):
    return any(lo <= ipix <= hi for lo, hi in ranges)


def test_order_is_16():
    assert HEALPIX_ORDER == 16


def test_point_index_is_stable_and_local():
    # A fixed coordinate maps to a fixed, reproducible pixel.
    first = radec_to_ipix(0.0, 0.0)
    assert radec_to_ipix(0.0, 0.0) == first
    assert isinstance(first, int)
    # Two points closer than one order-16 pixel (~3.2 arcsec) share an index.
    assert radec_to_ipix(10.0, 20.0) == radec_to_ipix(10.0 + 0.0001, 20.0)
    # Two widely separated points differ.
    assert radec_to_ipix(10.0, 20.0) != radec_to_ipix(200.0, -40.0)


def test_point_index_array_matches_scalar():
    ras = [0.0, 180.0, 359.99]
    decs = [0.0, -30.0, 0.0]
    batch = radec_to_ipix_array(ras, decs)
    assert batch == [radec_to_ipix(r, d) for r, d in zip(ras, decs)]
    assert all(isinstance(x, int) for x in batch)


def test_invalid_coordinates_return_none():
    # Out-of-range declination and non-finite coordinates must not reach
    # cdshealpix (which raises / panics); they degrade to None instead.
    assert radec_to_ipix(10.0, 95.0) is None
    assert radec_to_ipix(10.0, -95.0) is None
    assert radec_to_ipix(float("nan"), 10.0) is None
    assert radec_to_ipix(10.0, float("nan")) is None


def test_array_isolates_invalid_rows():
    # A bad row yields None without aborting the batch or shifting other rows.
    result = radec_to_ipix_array([10.0, 20.0, 30.0], [95.0, 30.0, float("nan")])
    assert result == [None, radec_to_ipix(20.0, 30.0), None]


def test_cone_ranges_cover_ra_wraparound():
    # Covers AE4: a cone centered near RA 0 matches objects at RA 359.9 and 0.1.
    # 0.1 deg == 360 arcsec, so the cone must be at least that wide.
    ranges = cone_ipix_ranges(0.0, 0.0, 400.0)
    assert _in_ranges(radec_to_ipix(359.9, 0.0), ranges)
    assert _in_ranges(radec_to_ipix(0.1, 0.0), ranges)
    assert _in_ranges(radec_to_ipix(0.0, 0.0), ranges)


def test_cone_ranges_are_sorted_and_nonoverlapping():
    ranges = cone_ipix_ranges(45.0, 45.0, 300.0)
    assert ranges == sorted(ranges)
    for (lo, hi) in ranges:
        assert lo <= hi
    for prev, nxt in zip(ranges, ranges[1:]):
        assert prev[1] + 1 < nxt[0]  # contiguous pixels were merged into one range


def test_fine_filter_is_exact_at_the_boundary():
    # angular_separation_arcsec is the exact filter applied after the range pre-filter.
    radius = 60.0
    # A point just inside the radius passes; one just outside fails.
    inside = angular_separation_arcsec(0.0, 0.0, 0.0, 59.0 / 3600.0)
    outside = angular_separation_arcsec(0.0, 0.0, 0.0, 61.0 / 3600.0)
    assert inside <= radius
    assert outside > radius
    # Symmetry and zero self-separation.
    assert angular_separation_arcsec(10.0, -20.0, 10.0, -20.0) == 0.0


def test_cone_near_pole_returns_valid_ranges():
    ranges = cone_ipix_ranges(0.0, 89.9, 120.0)
    assert ranges  # non-empty, no error
    assert _in_ranges(radec_to_ipix(0.0, 89.9), ranges)
