"""R6: build_catalog_payload coerces numpy/pandas scalars and null sentinels to
JSON-native values (no NaN token, no non-serializable types), lowercases keys,
and keeps a stable key set.

Also covers build_published_payload's coverage keys (R4): catalogs_skipped is a
sorted list and partial is true iff any catalog was skipped."""

import json

import numpy as np
import pandas as pd

from matching.payload import build_catalog_payload, build_published_payload


def test_coerces_numpy_and_nulls_to_json_native():
    values = {
        "MAG_G": np.int32(17),
        "MAG_R": np.float64(18.5),
        "FLAG": np.bool_(True),
        "MISS_NONE": None,
        "MISS_NAN": np.nan,
        "MISS_NAT": pd.NaT,
        "MISS_PDNA": pd.NA,
    }
    cols = list(values.keys())

    out = build_catalog_payload(values, cols)

    json.dumps(out)  # must not raise (no numpy types, no NaN token)
    assert out["mag_g"] == 17 and isinstance(out["mag_g"], int)
    assert out["mag_r"] == 18.5 and isinstance(out["mag_r"], float)
    assert out["flag"] is True
    for k in ("miss_none", "miss_nan", "miss_nat", "miss_pdna"):
        assert out[k] is None
    assert set(out.keys()) == {c.lower() for c in cols}


def _published(catalogs_skipped=None):
    return build_published_payload(
        9_000_000_001,
        180.0,
        -30.0,
        "gaia_dr3",
        "src-1",
        0.5,
        {"phot_g_mean_mag": 18.2},
        catalogs_skipped=catalogs_skipped,
    )


def test_published_payload_full_coverage_by_default():
    # No skipped catalogs -> covered every catalog: partial False, empty list.
    out = _published()

    json.dumps(out)  # published as JSON over Hopskotch; must not raise
    assert out["partial"] is False
    assert out["catalogs_skipped"] == []


def test_published_payload_marks_partial_and_sorts_skipped():
    # A skip stamps partial True and normalizes catalogs_skipped to a sorted list.
    out = _published(catalogs_skipped={"skymapper_dr4", "des_y6_gold"})

    assert out["partial"] is True
    assert out["catalogs_skipped"] == ["des_y6_gold", "skymapper_dr4"]
