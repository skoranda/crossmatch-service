---
title: "Coercing numpy/pandas scalars to JSON-native values across the LSDB to Django JSONField to Hopskotch boundary"
date: 2026-05-27
category: design-patterns
module: crossmatch/matching
problem_type: design_pattern
component: service_object
severity: medium
applies_when:
  - "Writing numpy or pandas scalar values (int16/int32/int64, float32/float64, np.bool_) into a Django JSONField or json.dumps"
  - "Loading or introspecting LSDB HATS catalog columns via lsdb.open_catalog"
  - "Requesting catalog columns that may collide with alert DataFrame columns under crossmatch(suffix_method='overlapping_columns')"
  - "Normalizing column names across surveys with inconsistent case (Gaia/SkyMapper lowercase, DES/DELVE uppercase)"
  - "Handling pandas null sentinels (None, NaN, NaT, pd.NA) destined for JSON"
related_components:
  - background_job
  - database
tags:
  - numpy-json-serialization
  - pandas-na
  - django-jsonfield
  - lsdb
  - hats-catalogs
  - hopskotch
  - type-coercion
  - column-collision
---

# Coercing numpy/pandas scalars to JSON-native values across the LSDB → Django JSONField → Hopskotch boundary

## Context

The crossmatch service pulls scientific values out of HATS catalogs (Gaia DR3, DES Y6 Gold, DELVE DR3 Gold, SkyMapper DR4) via LSDB and has to land them in two JSON-only sinks: a Django `JSONField` on the `CatalogMatch` record, and a JSON notification published over Hopskotch (Kafka via hop-client).

The friction is a type-system boundary. A crossmatch result is a pandas DataFrame; its cells are *not* Python scalars. Catalog flag and magnitude columns come back as numpy scalars (`np.int16`/`np.int32`/`np.int64`, `np.float32`/`np.float64`, `np.bool_`) and missing values arrive as a zoo of sentinels (`None`, float `nan`, `pd.NaT`, `pd.NA`). None of these are JSON-native:

- A Django `JSONField` cannot store a numpy scalar, and `json.dumps` cannot serialize one — you get `TypeError: Object of type int64 is not JSON serializable`.
- A float `nan` *does* pass through Python's `json` encoder, but it emits the bare token `NaN`, which is invalid JSON that strict parsers (and many Kafka consumers) reject.

On top of the dtype problem, the four catalogs disagree on column-name casing (Gaia/SkyMapper lowercase, DES/DELVE UPPERCASE, SkyMapper's coordinates carry a J2000 suffix: `raj2000`/`dej2000`), and LSDB's crossmatch will silently rename any catalog column that collides with an alert column. So the boundary needs both a value coercion and a key normalization, plus a couple of up-front guards so failures are loud and local instead of silent and catalog-wide.

## Guidance

### Lead practice: coerce every catalog value to a JSON-native scalar at the boundary

Centralize the numpy/pandas → JSON coercion in one small, dependency-light helper (`crossmatch/matching/payload.py`). Build the published/stored payload by mapping each declared column through it. The key ordering decisions:

- Match **abstract numpy types** (`np.integer`, `np.floating`, `np.bool_`), never concrete widths. Catalogs mix int16/int32/int64 and float32/float64; matching only `np.int64` would silently miss int16 flag columns.
- **Check bool before int.** Python `bool` is a subclass of `int`, so `isinstance(True, int)` is True — checking int first would turn `True` into `1`. (`np.bool_` is not a subclass of `np.integer`, but keeping bool first also keeps native Python bools correct.)
- **Recognize all missing-value sentinels with `pd.isna`, guarded by `np.ndim(value) == 0`.** `pd.isna` uniformly catches `None`/`nan`/`NaT`/`pd.NA`, but called on an *array* it returns an array whose truth value raises `ValueError: The truth value of an array with more than one element is ambiguous`. Guard to scalar first.
- **Emit a stable key set.** Build one key per declared column for every row; a value missing for this row becomes JSON `null`. Downstream consumers then see a consistent schema per catalog.
- **Keep the helper free of LSDB and Django imports** so it is unit-testable in isolation (it only needs numpy/pandas to recognize the types).

### Supporting practice: load and validate catalog subset columns up front

`lsdb.open_catalog(url)` with no `columns` argument loads only the catalog's **default** columns — your requested science column may simply not be there. Two parts:

- Introspect the *full* schema with `lsdb.open_catalog(url, columns="all").columns`, then load the subset you actually want with an explicit `columns=[...]`.
- Validate requested columns against the full schema before loading, and raise a clear error naming the offending column. Otherwise a misspelled or wrong-case name surfaces as a cryptic parquet error deep inside `.compute()`, where the crossmatch loop swallows it as a generic per-catalog failure. See `_get_catalog` in `crossmatch/matching/catalog.py`.

### Supporting practice: normalize case while preserving meaningful suffixes

Because survey column casing is inconsistent, lowercase the payload keys (`WAVG_MAG_PSF_G` → `wavg_mag_psf_g`). Already-lowercase names pass through unchanged, so SkyMapper's `raj2000`/`dej2000` are preserved rather than mangled.

### Supporting practice: guard against crossmatch suffix collisions

`crossmatch(..., suffix_method='overlapping_columns')` renames only the columns that collide between the two catalogs. If a requested catalog column shares a name with an alert column (`uuid`, `lsst_diaObject_diaObjectId`, `ra_deg`, `dec_deg`), it gets silently `_catalog`-suffixed and the payload key mapping breaks. Reject such requests up front with an explicit `_ALERT_COLUMNS` collision check (`crossmatch/matching/catalog.py`).

### Supporting practice: build per-row defensively, append in lockstep

In the task loop (`crossmatch/tasks/crossmatch.py`), wrap each row's build in `try/except → continue`, not the whole loop. A whole-loop guard would discard *all* of a catalog's matches on a single bad row, and because the batch unconditionally transitions to `MATCHED` afterward, that loss is permanent. Append the `CatalogMatch` and `Notification` records only after both objects are constructed, so the two lists stay aligned.

## Why This Matters

Concrete failure modes this pattern prevents:

- **`TypeError: Object of type int64 is not JSON serializable`** — a numpy scalar reaching the Django `JSONField` or `json.dumps` crashes the write/publish. Coercion at the boundary removes the numpy types entirely.
- **Invalid bare `NaN` token in JSON** — a float `nan` slips past Python's encoder but produces non-standard JSON that strict consumers reject. Mapping missing values to `None` (JSON `null`) keeps the output spec-compliant.
- **Silently dropped flag columns** — matching `np.int64` only would skip int16/int32 flag columns from DELVE/SkyMapper, dropping science data with no error. Abstract-type matching catches every integer width.
- **Booleans corrupted to integers** — checking int before bool turns `True` into `1`, quietly changing the published value's type.
- **Cryptic deep-stack failures hidden as generic per-catalog errors** — a wrong-case column name otherwise blows up inside `.compute()` and the loop logs it as an opaque catalog failure; the up-front schema validation names the exact offender.
- **Silent suffix collisions** — a future payload column named like an alert column would be `_catalog`-suffixed and break key mapping with no warning; the collision guard turns that into a clear `ValueError`.
- **Whole-catalog data loss** — one malformed row under a loop-level guard would discard every match for that catalog permanently. The per-row guard limits the blast radius to the one bad row.

## When to Apply

- **Any time numpy/pandas scalars cross into a JSON, Kafka, or Django `JSONField` boundary** — serializing a DataFrame row, building an API response from pandas, publishing to a message bus. This is the trigger for the scalar-coercion helper.
- **Whenever you load a subset of columns from a HATS catalog (or any wide parquet-backed catalog)** — introspect the full schema with `columns="all"` and validate before loading, so requested columns are confirmed present.
- **When mapping columns across case-inconsistent data sources** — multiple surveys/vendors with different casing conventions; normalize keys while preserving meaningful suffixes like J2000.
- **When using an LSDB/join operation with overlapping-column suffixing** — guard against silent renames where output and input column namespaces can collide.

## Examples

The verbatim helper (`crossmatch/matching/payload.py`):

```python
import numpy as np
import pandas as pd


def _to_json_scalar(value):
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
    return {
        col.lower(): _to_json_scalar(values.get(col))
        for col in payload_columns
    }
```

Concrete before → after values:

| Input (catalog-native) | Output (JSON-native) | Why |
|---|---|---|
| `np.int64(16)` (e.g. `BDF_FLAGS`) | `16` (Python `int`) | abstract-int match; flag stays int, not float |
| `np.int16(4)` (DELVE flag) | `4` (Python `int`) | abstract-int match catches narrow widths |
| `np.float64(nan)` (`DNF_Z`) | `None` → JSON `null` | `pd.isna` sentinel; no invalid `NaN` token |
| `pd.NA` (nullable-int missing) | `None` → JSON `null` | same uniform sentinel handling |
| `np.bool_(True)` | `True` (Python `bool`) | bool checked before int, so not coerced to `1` |
| key `WAVG_MAG_PSF_G` (DES UPPERCASE) | key `wavg_mag_psf_g` | lowercase normalization |
| key `raj2000` (SkyMapper) | key `raj2000` | already lowercase, J2000 suffix preserved |
| declared column absent from row | key present, value `None` | stable key set per catalog |

Verification approach (auto memory [claude]): this repo has **no functioning Python test runner**, so the helper was verified by a standalone script `scripts/check_payload.py` (loads `payload.py` by file path to avoid importing the Django package) with assertions covering lowercase keying, case-flip, J2000 preservation, NaN/`pd.NA`/native-`nan` → `None`, int16/int32/int64 coercion, bool staying bool, the stable key set, and full `json.dumps` serializability (including `NaN` rendering as `null`). It is run in a throwaway `/tmp` venv because the local venvs have dead python3.12 symlinks (system is python3.13).

## Related

- `docs/plans/2026-05-27-001-feat-catalog-specific-payload-columns-plan.md` — the completed plan that produced this work (primary lineage).
- `docs/brainstorms/2026-05-11-crossmatch-payload-columns-community-draft.md` — the origin brainstorm (community review draft of the payload-columns feature).
- `docs/plans/2026-03-12-002-feat-publish-crossmatch-to-hopskotch-plan.md` — establishes the Hopskotch/Kafka JSON publish path the coerced payload flows into.
- `docs/brainstorms/2026-03-07-lowercase-column-names-brainstorm.md` — background for the lowercase key-normalization sub-practice.
- `docs/brainstorms/2026-03-11-lsdb-suffix-futurewarning-brainstorm.md` — background for the `crossmatch` overlapping-columns suffix collision-guarding sub-practice.
