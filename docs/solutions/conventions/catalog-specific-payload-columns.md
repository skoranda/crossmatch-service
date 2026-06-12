---
title: "Declarative per-catalog payload_columns in CROSSMATCH_CATALOGS"
date: 2026-06-12
category: conventions
module: crossmatch/project + crossmatch/matching
problem_type: convention
component: service_object
severity: medium
related_components:
  - background_job
applies_when:
  - "Adding a new HATS catalog to CROSSMATCH_CATALOGS"
  - "Adding, removing, or reordering columns in an existing catalog's published Hopskotch payload"
  - "An upstream catalog renames, drops, or changes the case of a column"
  - "Reviewing a PR that touches the catalog config or the published-payload contract"
tags:
  - catalog-config
  - payload
  - declarative-config
  - hats
  - lsdb
  - hopskotch
  - settings
  - onboarding
---

# Declarative per-catalog `payload_columns` in `CROSSMATCH_CATALOGS`

## Context

The crossmatch service publishes one JSON record per (alert, catalog) match over Hopskotch. The four HATS catalogs it matches against (Gaia DR3, DES Y6 Gold, DELVE DR3 Gold, SkyMapper DR4) carry different observables: Gaia has parallax / proper motion, DES and DELVE have shape and photo-z, DELVE drops DES's Y band, SkyMapper exposes only PSF photometry over six bands. A single shared payload schema is not workable — what publishes for a given match has to be catalog-specific.

The earliest version of the service shipped a fixed minimal payload (`diaObjectId`, RA/Dec, catalog name, source id, separation) that omitted everything astronomers act on. The catalog-specific payload effort (`feature/catalog-specific-payload`, PR #44) replaced that with a **per-catalog declarative publish contract** living in Django settings. This doc captures the convention.

The boundary-level value-coercion that backs this convention (numpy/pandas scalars → JSON-native values, NaN/`pd.NA` → `None`, lowercase keys, suffix-collision guard, per-row defensive build) is documented separately in `docs/solutions/design-patterns/coerce-numpy-pandas-scalars-to-json.md` — this doc references that one for the depth on value handling rather than duplicating it.

## Guidance

The convention: **each entry in `settings.CROSSMATCH_CATALOGS` declares an explicit `payload_columns` list in upstream-native column names and case.** That list is the single source of truth for what publishes for that catalog. Three modules consume it:

- `crossmatch/matching/catalog.py` — `_load_columns` and `_get_catalog` use it to load exactly those columns from the HATS catalog (deduplicating against `source_id_column` / `ra_column` / `dec_column`), and validate them up front.
- `crossmatch/matching/payload.py` — `build_catalog_payload(values, payload_columns)` emits one key per declared column for every row, in declared order.
- `crossmatch/tasks/crossmatch.py` — the batch task reads `payload_columns` from each catalog config and passes it to the builder.

Rules of the convention:

**1. Source-native casing in the config.** Gaia and SkyMapper are lowercase; DES and DELVE are UPPERCASE; SkyMapper's coordinates carry a J2000 suffix (`raj2000`/`dej2000`). The config preserves what the upstream actually uses — reviewers can cross-check against `docs/references/<catalog>-columns.md`. Lowercasing happens at publish time only, not in the config.

**2. No code-driven derivation.** Nothing computes the publish column list from the matched DataFrame or from a catalog schema. Upstream schema drift then cannot silently change the public contract — the contract changes only when someone edits `settings.py`, and the diff is reviewable.

**3. `payload_columns` is a load-time gate, not just a publish-time selector.** The HATS loader fetches exactly the configured columns (less I/O than loading everything), and validates them against the catalog's full schema at load time. Misspelled or wrong-case names fail loudly at startup with a clear `ValueError` naming the offender and pointing at the per-catalog reference doc — not as an opaque parquet error deep inside `.compute()` that the per-catalog try/except in the batch task would swallow as a generic catalog failure.

**4. `source_id_column`, `ra_column`, `dec_column` follow the same case rule.** They are not separately published, but the loader dedups them against `payload_columns`, so they must use the upstream-native name. DES/DELVE declare `RA`/`DEC` because that's how the catalogs name the column; SkyMapper declares `raj2000`/`dej2000` for the same reason.

**5. No collision with alert columns.** The reserved set `_ALERT_COLUMNS = {'uuid', 'lsst_diaObject_diaObjectId', 'ra_deg', 'dec_deg'}` is enforced by the loader. A `payload_columns` entry that collided with one of those would be silently `_catalog`-suffixed by LSDB's `crossmatch(suffix_method='overlapping_columns')`, and the published payload key would silently disappear. The collision guard refuses such configs explicitly. None of today's payload columns collide; the guard exists for the next catalog or column added.

For the per-catalog authoritative column lists (the source of truth for what columns exist with what casing), see:

- `docs/references/gaia_dr3-columns.md`
- `docs/references/des_y6_gold-columns.md`
- `docs/references/delve_dr3_gold-columns.md`
- `docs/references/skymapper_dr4-columns.md`

For the depth on value-handling at the publish boundary, see `docs/solutions/design-patterns/coerce-numpy-pandas-scalars-to-json.md`.

## Why This Matters

- **The published payload is the product.** A declarative `payload_columns` list makes every change to the contract visible in a `settings.py` diff. A code-driven payload would let upstream schema drift silently change what astronomers receive without any review trail.
- **Onboarding a catalog requires declaring its publish columns.** "Add a catalog" becomes "add an entry to `CROSSMATCH_CATALOGS` with `payload_columns`" — the published contract is part of the onboarding artifact, not a follow-up.
- **Misspellings fail at startup, not in the loop.** Because the loader validates `payload_columns` against the catalog's full HATS schema at load time, a typo surfaces immediately with a named error. Without the up-front gate, the same typo would surface as an opaque per-catalog failure inside `.compute()`, get logged as a generic failure by the per-catalog try/except, and silently drop the catalog's matches for that batch (the batch then unconditionally transitions to `MATCHED`, making the loss permanent — there is no retry pathway).
- **Alert-column collisions are blocked at the config layer.** A future payload column that happens to match `uuid` / `lsst_diaObject_diaObjectId` / `ra_deg` / `dec_deg` would otherwise be silently renamed by LSDB's crossmatch overlap-suffixing, and the published key would disappear. The `_ALERT_COLUMNS` guard turns that into an explicit `ValueError` at load time.
- **Less I/O.** The loader passes the configured columns to `lsdb.open_catalog(url, columns=requested)` rather than fetching the catalog's full column set.

## When to Apply

- Adding a new HATS catalog to `CROSSMATCH_CATALOGS`. The catalog's `payload_columns` is part of the change, not deferred.
- Adding or removing columns from an existing catalog's published payload. The diff lives in `settings.py`, not in the matching modules.
- Upstream renames or recases a column (DR-version bump, schema cleanup) — update the corresponding `payload_columns` entry to the new native name, and re-check `docs/references/<catalog>-columns.md` so the reference docs stay accurate.
- Reviewing a PR that touches catalog config: confirm new entries use upstream-native case (cross-check against `docs/references/<catalog>-columns.md`) and don't intersect `_ALERT_COLUMNS`. The loader's runtime guards back-stop these, but catching them in review is cheaper than waiting for a startup failure.

This convention is specific to this codebase. The broader pattern — declarative per-source publish contracts at a heterogeneous tabular boundary — generalizes to other multi-vendor publish pipelines, but the rules above are stated against the crossmatch service's actual config shape and module names.

## Examples

Excerpt from `crossmatch/project/settings.py` (verbatim shape, columns abbreviated for readability):

```python
CROSSMATCH_CATALOGS = [
    {
        'name': 'gaia_dr3',
        'hats_url': GAIA_HATS_URL,
        'source_id_column': 'source_id',
        'ra_column': 'ra',
        'dec_column': 'dec',
        # Upstream-native case; Gaia is lowercase.
        'payload_columns': [
            'phot_g_mean_mag', 'phot_bp_mean_mag', 'phot_rp_mean_mag',
            'ra', 'dec', 'parallax', 'parallax_error',
            'pmra', 'pmdec', 'ref_epoch',
            'classprob_dsc_combmod_star', 'classprob_dsc_combmod_galaxy',
            'ruwe', 'astrometric_excess_noise',
            # ...
        ],
    },
    {
        'name': 'des_y6_gold',
        'hats_url': DES_HATS_URL,
        'source_id_column': 'COADD_OBJECT_ID',
        'ra_column': 'RA',
        'dec_column': 'DEC',
        # DES is UPPERCASE. RA/DEC declared uppercase so the loader dedups
        # them against ra_column/dec_column instead of requesting a
        # non-existent lowercase column.
        'payload_columns': [
            'WAVG_MAG_PSF_G', 'WAVG_MAG_PSF_R', 'WAVG_MAG_PSF_I',
            'WAVG_MAG_PSF_Z', 'WAVG_MAG_PSF_Y',
            'RA', 'DEC',
            'BDF_T', 'BDF_G_1', 'BDF_G_2',
            'DNF_Z', 'DNF_ZSIGMA',
            'EXT_MASH',
            'FLAGS_GOLD', 'BDF_FLAGS',
            # ...
        ],
    },
    {
        'name': 'skymapper_dr4',
        'hats_url': SKYMAPPER_HATS_URL,
        'source_id_column': 'object_id',
        'ra_column': 'raj2000',     # J2000 suffix preserved end-to-end
        'dec_column': 'dej2000',
        # Lowercase upstream; raj2000/dej2000 keep the J2000 suffix in
        # the published payload too (build_catalog_payload lowercases keys
        # but the suffix is already there).
        'payload_columns': [
            'u_psf', 'v_psf', 'g_psf', 'r_psf', 'i_psf', 'z_psf',
            'raj2000', 'dej2000',
            'class_star',
            'flags', 'nimaflags', 'ngood',
            # ...
        ],
    },
]
```

The load-time gates that enforce the convention live in `crossmatch/matching/catalog.py` and run on first use of each catalog (the loader is module-level cached):

```python
_ALERT_COLUMNS = {'uuid', 'lsst_diaObject_diaObjectId', 'ra_deg', 'dec_deg'}


def _load_columns(catalog_config):
    return list(dict.fromkeys([
        catalog_config['source_id_column'],
        catalog_config['ra_column'],
        catalog_config['dec_column'],
        *catalog_config.get('payload_columns', []),
    ]))


def _get_catalog(catalog_config):
    name = catalog_config['name']
    if name not in _catalog_cache:
        url = catalog_config['hats_url']
        requested = _load_columns(catalog_config)

        collisions = [c for c in requested if c in _ALERT_COLUMNS]
        if collisions:
            raise ValueError(
                f"{name}: requested columns {collisions} collide with alert "
                f"columns; the crossmatch would suffix them and break payload "
                f"key mapping. Rename or drop them from payload_columns."
            )

        # columns="all" loads the FULL schema for introspection; default
        # would be only the catalog's "default" columns and would miss real ones.
        available = set(lsdb.open_catalog(url, columns="all").columns)
        missing = [c for c in requested if c not in available]
        if missing:
            raise ValueError(
                f"{name}: requested columns not found in catalog schema: "
                f"{missing}. Check name/case against "
                f"docs/references/{name}-columns.md."
            )

        _catalog_cache[name] = lsdb.open_catalog(url, columns=requested)
    return _catalog_cache[name]
```

The publish-side builder is a one-liner over the same `payload_columns` list — depth on value coercion lives in the design-pattern doc cross-referenced below:

```python
# crossmatch/matching/payload.py
def build_catalog_payload(values, payload_columns):
    return {
        col.lower(): _to_json_scalar(values.get(col))
        for col in payload_columns
    }
```

A column declared in `payload_columns` that is missing from a given row appears as JSON `null`, not absent — the key set is stable per catalog regardless of per-row nulls, so consumers can rely on `payload[k]` not raising `KeyError`.

## Related

- `docs/solutions/design-patterns/coerce-numpy-pandas-scalars-to-json.md` — depth on the boundary value-handling sub-practice (numpy/pandas → JSON-native, `pd.isna` sentinels → `None`, lowercase keying with J2000 preservation, suffix-collision guard, per-row defensive build, verification approach via standalone script in a throwaway venv).
- `docs/plans/2026-05-27-001-feat-catalog-specific-payload-columns-plan.md` — the completed plan that produced this convention.
- `docs/brainstorms/2026-05-11-crossmatch-payload-columns-community-draft.md` — origin community-review brainstorm; §8 core column set is what the implementation realized.
- `docs/brainstorms/2026-05-04-payload-columns-community-draft-brainstorm.md` — predecessor community draft incorporating PI v1 feedback.
- `docs/brainstorms/2026-04-27-payload-columns-by-keyword-brainstorm.md` — original PI-keyword payload-selection draft; names the `feature/catalog-specific-payload` branch.
- `docs/plans/2026-03-12-002-feat-publish-crossmatch-to-hopskotch-plan.md` — defines the Hopskotch publish path the payload flows into.
- `docs/references/gaia_dr3-columns.md`, `docs/references/des_y6_gold-columns.md`, `docs/references/delve_dr3_gold-columns.md`, `docs/references/skymapper_dr4-columns.md` — authoritative per-catalog column lists (the source of truth for upstream-native names and casing).
- `docs/solutions/conventions/dependency-pin-upgrade-pattern-2026-05-12.md` — adjacent convention: LSDB / numpy / pandas pins must move atomically across pin sites to stay aligned with the Dask cluster's Python+library versions.
