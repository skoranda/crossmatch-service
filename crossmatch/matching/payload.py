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
