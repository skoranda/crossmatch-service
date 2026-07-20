"""Build the catalog-specific payload from a crossmatched row.

A crossmatch result carries catalog columns under their upstream-native names
and dtypes — numpy scalars (int16/int32/int64, float32/float64, bool_) and
pandas missing values. The published payload needs lowercase keys and plain
JSON-native Python scalars, because the values are stored in a Django
``JSONField`` and published as JSON over Hopskotch (a ``JSONField`` cannot hold
numpy scalars, and ``json`` cannot serialize them).

This module is intentionally free of LSDB and Django imports so it can be
exercised in isolation; numpy and pandas are used only to recognize the scalar
types and missing-value sentinels that flow out of the crossmatch DataFrame.
"""

import numpy as np
import pandas as pd


def _to_json_scalar(value):
    """Coerce one catalog value to a JSON-native scalar.

    Missing values (``None``, NaN, NaT, ``pd.NA``) become ``None``. numpy
    integers / floats / booleans become their Python equivalents; strings pass
    through; anything else is stringified as a last resort.
    """
    # pd.isna recognizes None, float nan, np.nan, pd.NaT and pd.NA uniformly.
    # Guard to scalars first: pd.isna on an array returns an array, whose truth
    # value is ambiguous. Crossmatch rows yield scalars, so this is just safety.
    if value is None or (np.ndim(value) == 0 and pd.isna(value)):
        return None
    # bool before int: Python bool is a subclass of int, and np.bool_ is not.
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value)
    if isinstance(value, str):
        return value
    # Some other numpy scalar: unwrap to a Python object and retry once.
    item = getattr(value, "item", None)
    if callable(item):
        return _to_json_scalar(item())
    return str(value)


def build_catalog_payload(values, payload_columns):
    """Return the lowercase-keyed, JSON-native payload for one matched row.

    Args:
        values: Mapping of upstream-native column name -> raw value for the row
            (numpy scalars / pandas missing values as they come off the
            crossmatch result DataFrame).
        payload_columns: Ordered list of upstream-native column names to include
            (a catalog's configured ``payload_columns``).

    Returns:
        Dict keyed by the lowercased column name, in ``payload_columns`` order.
        Every declared column is present; a value that is missing or NaN for
        this row is ``None`` (stable key set per catalog). Keys are lowercased
        (e.g. ``WAVG_MAG_PSF_G`` -> ``wavg_mag_psf_g``); already-lowercase names
        such as SkyMapper's ``raj2000`` are unchanged, so the J2000 suffix is
        preserved.
    """
    return {
        col.lower(): _to_json_scalar(values.get(col))
        for col in payload_columns
    }


def build_published_payload(
    dia_object_id,
    source_ra_deg,
    source_dec_deg,
    catalog_name,
    catalog_source_id,
    separation_arcsec,
    catalog_payload,
    catalogs_skipped=None,
):
    """Build the per-match payload published over Hopskotch.

    Single source of truth for the published payload shape, called by both the
    crossmatch publish path (``tasks/crossmatch.py``) and the read-model API's
    ``full`` detail level, so the two cannot drift. The ``ra``/``dec`` are the
    matched catalog-source coordinates (not the alert object's position); the
    per-catalog columns live nested under ``catalog_payload``.

    Args:
        dia_object_id: The alert's ``diaObjectId`` (coerced to int64).
        source_ra_deg: Matched catalog source right ascension in degrees.
        source_dec_deg: Matched catalog source declination in degrees.
        catalog_name: Catalog the match came from (e.g. ``gaia_dr3``).
        catalog_source_id: Source identifier in that catalog.
        separation_arcsec: Angular separation between alert and source, arcsec.
        catalog_payload: The catalog-specific payload dict (see
            :func:`build_catalog_payload`).
        catalogs_skipped: Names of catalogs skipped in this crossmatch batch
            because their reads persistently failed (``None`` / empty means the
            crossmatch covered every configured catalog). Drives ``partial``.
            The read-model API serves a stored match with no batch context, so it
            passes ``None`` here (the published Hopskotch payload carries the real
            per-batch value).

    Returns:
        A JSON-native dict with stable keys ``diaObjectId``, ``ra``, ``dec``,
        ``catalog_name``, ``catalog_source_id``, ``separation_arcsec``,
        ``catalog_payload``, ``catalogs_skipped`` (sorted list), and ``partial``
        (true iff any catalog was skipped).
    """
    skipped = sorted(catalogs_skipped) if catalogs_skipped else []
    return {
        'diaObjectId': int(dia_object_id),
        'ra': float(source_ra_deg),
        'dec': float(source_dec_deg),
        'catalog_name': catalog_name,
        'catalog_source_id': catalog_source_id,
        'separation_arcsec': float(separation_arcsec),
        'catalog_payload': catalog_payload,
        'catalogs_skipped': skipped,
        'partial': bool(skipped),
    }
