"""R6: build_catalog_payload coerces numpy/pandas scalars and null sentinels to
JSON-native values (no NaN token, no non-serializable types), lowercases keys,
and keeps a stable key set."""

import json

import numpy as np
import pandas as pd

from matching.payload import build_catalog_payload


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
