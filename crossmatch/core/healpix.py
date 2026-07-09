"""HEALPix spatial helpers for the alert read model.

Point indexing and cone/region range queries over the alert table's
``healpix_ipix`` column, using cdshealpix NESTED at a single fixed order so that
ingest (point -> ipix) and query (cone -> ipix ranges) stay in the same
tessellation. cdshealpix is already available as a locked transitive dependency
via ``hats`` (see the plan's KTD1), so no new dependency is introduced.
"""

from __future__ import annotations

import math

import astropy.units as u
import numpy as np
from cdshealpix import nested

# NESTED order 16 -> nside 65536, ~3.2 arcsec pixels. This value is persisted in
# every ``healpix_ipix`` (backfilled and go-forward); changing it silently mixes
# resolutions in the column and would require re-backfilling every row, so it is
# load-bearing data, not a free retune (see the plan's KTD4).
HEALPIX_ORDER = 16


def radec_to_ipix(ra_deg: float, dec_deg: float) -> int:
    """Return the NESTED HEALPix pixel index for one sky position.

    Args:
        ra_deg: Right ascension in degrees.
        dec_deg: Declination in degrees.

    Returns:
        The order-``HEALPIX_ORDER`` NESTED pixel index as a Python int.
    """
    ipix = nested.lonlat_to_healpix(
        np.array([ra_deg], dtype=float) * u.deg,
        np.array([dec_deg], dtype=float) * u.deg,
        depth=HEALPIX_ORDER,
    )
    return int(ipix[0])


def radec_to_ipix_array(ra_deg, dec_deg) -> list[int]:
    """Return NESTED HEALPix pixel indices for a batch of sky positions.

    Vectorized companion to :func:`radec_to_ipix` for bulk work such as the
    existing-corpus backfill, where a per-row scalar call would pay the
    array-construction and native-call overhead once per row.

    Args:
        ra_deg: Sequence of right ascensions in degrees.
        dec_deg: Sequence of declinations in degrees, aligned with ``ra_deg``.

    Returns:
        A list of order-``HEALPIX_ORDER`` NESTED pixel indices (Python ints),
        one per input coordinate pair, in input order.
    """
    ipix = nested.lonlat_to_healpix(
        np.asarray(ra_deg, dtype=float) * u.deg,
        np.asarray(dec_deg, dtype=float) * u.deg,
        depth=HEALPIX_ORDER,
    )
    return [int(x) for x in ipix]


def cone_ipix_ranges(
    ra_deg: float, dec_deg: float, radius_arcsec: float
) -> list[tuple[int, int]]:
    """Return contiguous NESTED pixel ranges covering a cone.

    The ranges are inclusive ``[lo, hi]`` bounds suitable for a SQL
    ``healpix_ipix BETWEEN lo AND hi`` predicate. ``cone_search`` is called with
    ``flat=True`` so every returned pixel is at order ``HEALPIX_ORDER`` (the
    multi-resolution default would mix depths, whose indices are not comparable
    to the stored order-16 values); adjacent pixels are merged into ranges. The
    cover is inclusive and may include pixels whose centers lie just outside the
    radius, so callers must apply an exact :func:`angular_separation_arcsec`
    fine-filter to the candidate rows.

    Args:
        ra_deg: Cone-center right ascension in degrees.
        dec_deg: Cone-center declination in degrees.
        radius_arcsec: Cone radius in arcseconds.

    Returns:
        A sorted list of inclusive ``(lo, hi)`` NESTED pixel ranges.
    """
    ipix_arr, _depths, _fully_covered = nested.cone_search(
        lon=ra_deg * u.deg,
        lat=dec_deg * u.deg,
        radius=radius_arcsec * u.arcsec,
        depth=HEALPIX_ORDER,
        flat=True,
    )
    pixels = np.unique(np.asarray(ipix_arr, dtype=np.int64))
    return _merge_contiguous(pixels)


def _merge_contiguous(pixels) -> list[tuple[int, int]]:
    """Merge a sorted iterable of pixel indices into contiguous ``[lo, hi]`` ranges."""
    ranges: list[tuple[int, int]] = []
    for value in pixels:
        pix = int(value)
        if ranges and pix == ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], pix)
        else:
            ranges.append((pix, pix))
    return ranges


def angular_separation_arcsec(
    ra1_deg: float, dec1_deg: float, ra2_deg: float, dec2_deg: float
) -> float:
    """Return the great-circle separation between two sky positions, in arcsec.

    Uses the haversine formula, which stays numerically stable at the small
    separations a cone fine-filter cares about. This is the exact filter applied
    after the :func:`cone_ipix_ranges` pre-filter narrows candidates by pixel.

    Args:
        ra1_deg: First position right ascension in degrees.
        dec1_deg: First position declination in degrees.
        ra2_deg: Second position right ascension in degrees.
        dec2_deg: Second position declination in degrees.

    Returns:
        Angular separation in arcseconds.
    """
    ra1 = math.radians(ra1_deg)
    dec1 = math.radians(dec1_deg)
    ra2 = math.radians(ra2_deg)
    dec2 = math.radians(dec2_deg)
    d_dec = dec2 - dec1
    d_ra = ra2 - ra1
    hav = (
        math.sin(d_dec / 2.0) ** 2
        + math.cos(dec1) * math.cos(dec2) * math.sin(d_ra / 2.0) ** 2
    )
    ang_rad = 2.0 * math.asin(min(1.0, math.sqrt(hav)))
    return math.degrees(ang_rad) * 3600.0
