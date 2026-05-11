# Catalog Payload Columns (Community Review Draft)

**Date:** 2026-05-11

**Status:** Draft for alert broker community review

## 1. Summary

This document proposes a concrete **core** column set that downstream
subscribers will receive when a Rubin DIA object matches a row in one of
our four crossmatch catalogs (Gaia DR3, DES Y6 Gold, DELVE DR3 Gold,
SkyMapper DR4). It is circulating to gather broker-community input before
implementation.

### 1.1 Aims

- **Pick the columns** the crossmatch service will publish to downstream
  subscribers, organized by the keyword categories the PI identified
  (brightness, location, shape, photo-z, classification, quality).
- **Document concrete choices** — photometry default, multi-band rollup,
  quality flag baseline, magnitude system, payload data types — open to
  community pushback before implementation.
- **Be specific enough** that planning and implementation can begin.

The catalog set itself (the four above) is fixed for this iteration.
Adding new catalogs, companion tables (Gaia BP/RP spectra, QSO/galaxy
candidates, DES Y6 metacal, etc.), and an optional / extended payload
tier beyond the core are all out of scope here — see §10.

---

## 2. Problem Frame

The crossmatch service ingests DIA-object alerts from multiple
brokers, performs spatial crossmatches against several wide-area
catalogs, and (in the near future) will publish a per-match
payload to downstream subscribers via Hopskotch.  Today the
matched-row payload field is empty: only `source_id`, `ra`, `dec`
are loaded from the catalog side, and no columns are propagated to
subscribers.

The PI, Gautham Narayan, identified the kinds of catalog information
that matter to downstream users — brightness, location, shape,
photo-z, and classification — to which this draft adds a `quality`
bucket for footprint flags and PSF-fit diagnostics. Each keyword maps
onto specific columns differently per catalog, and several keywords
have multiple plausible readings. This draft proposes a concrete
per-keyword × per-catalog column set for community review.

---

## 3. Actors

- A1. **Rubin transient and multi-messenger followup teams** — alert
  brokers, ToO teams, multi-messenger groups consuming DIA-object alerts
  and the matched-catalog payload. Tend to care most about PSF photometry
  and a fast star/galaxy/QSO call.
- A2. **Galaxy / host-science groups** — researchers using crossmatch
  alerts to study DIA-object hosts, photo-z, morphology. Tend to care most
  about AUTO/BDF photometry, photo-z, shape parameters.
- A3. **Crossmatch service maintainers** — own the payload schema, the
  column-loading code, and the Hopskotch publishing path.
- A4. **Project PI** — has articulated the initial keyword set, and
  will sign off on the final core list once community input is incorporated.

---

## 4. Catalogs in scope

| Key             | Catalog          | HATS source                                               | Upstream column-name case   |
| --------------- | ---------------- | --------------------------------------------------------- | --------------------------- |
| `gaia_dr3`      | Gaia DR3         | `s3://stpubdata/gaia/gaia_dr3/public/hats`                | lowercase                   |
| `des_y6_gold`   | DES Y6 Gold      | `https://data.lsdb.io/hats/des/des_y6_gold`               | UPPERCASE                   |
| `delve_dr3_gold`| DELVE DR3 Gold   | `https://data.lsdb.io/hats/delve/delve_dr3_gold`          | UPPERCASE                   |
| `skymapper_dr4` | SkyMapper DR4    | `https://data.lsdb.io/hats/skymapper_dr4/catalog`         | lowercase, J2000 suffix     |

The published payload normalizes all column names to lowercase regardless
of the upstream case — `WAVG_MAG_PSF_G` becomes `wavg_mag_psf_g`, etc.
Catalog-native semantics are preserved in the name; only the case is
changed. SkyMapper's `raj2000` / `dej2000` keep the J2000 epoch suffix
since it carries information. Per-catalog column lists in §8 use the
lowercased payload names.

No new catalogs and no companion tables (Gaia BP/RP spectra, QSO/galaxy
candidates, DES Y6 metacal, etc.) are added by this proposal, but
additional catalogs will be incorporated in a later release of the
crossmatch service.

---

## 5. How column existence was verified

Every column name proposed below has been confirmed against the parquet
`_common_metadata` schema of the live HATS catalog as currently hosted on
`data.lsdb.io` (and the schema-identical Gaia DR3 mirror on AWS). This
verifies that each column **exists** in the catalog with a known dtype;
semantic interpretations (e.g., `EXT_MASH` encoding values, units of
`BDF_T`, the recommended-default status of `WAVG_MAG_PSF` vs alternatives)
come from catalog release notes and are part of what we are asking the
community to confirm. Per-catalog column listings, types, and counts are at:

- [`docs/references/gaia_dr3-columns.md`][gaia-cols] (153 columns)
- [`docs/references/des_y6_gold-columns.md`][des-cols] (337 columns)
- [`docs/references/delve_dr3_gold-columns.md`][delve-cols] (253 columns)
- [`docs/references/skymapper_dr4-columns.md`][skymapper-cols] (122 columns)

If any column below is unfamiliar, it is in the live catalog — see the
references for dtype.

---

## 6. Keyword interpretation

| Keyword                  | Interpretation in this draft                                                                       | 
| ------------------------ | -------------------------------------------------------------------------------------------------- | 
| brightness               | Magnitudes (per-band where applicable).                                                            | 
| location                 | Sky position, position uncertainty (where available), proper motion, parallax (Gaia only).         | 
| shape                    | Galaxy shape parameters: ellipticity, semi-axes, BDF size and de Vaucouleurs fraction.             | 
| distributions / redshift | Photo-z **point estimate** (and width). Not stellar RV. Not SED / spectrum summary.                |
| classification           | Star / galaxy / QSO label or probability.                                                          |
| quality                  | Quality / footprint flags and PSF-fit diagnostics.                                                 |

### 6.1 Notes on "distributions" / "redshift"

In this proposal, this bucket means photo-z only. It excludes
SED / spectrum summaries (Gaia BP/RP spectra, etc.) and stellar radial
velocity. Gaia DR3's `radial_velocity` is **not** part of the core
payload.

For DES Y6 Gold and DELVE DR3 Gold this collapses to the DNF photo-z
columns (`dnf_z`, `dnf_zsigma`). For Gaia DR3 main and SkyMapper DR4, no
photo-z exists in the live HATS schemas, so this keyword has no
contribution from those catalogs in the core payload.

The photo-z payload is the **point estimate plus its width**, not the
full p(z) PDF. No HATS catalog in scope publishes a p(z) PDF, so the
question of whether to ship one does not arise here.

---

## 7. Key decisions

1. **Single tier (core only) for now.** This proposal defines only the
   core payload. An optional / extended tier may be added later after
   community input shapes the core.
2. **Keyword set excludes `moments`, `spiral`, `elliptical`.** These
   keywords are not in scope for the core payload.
3. **No stellar RV in `redshift`.** Gaia DR3 `radial_velocity` is excluded.
   The redshift / distributions buckets are about photo-z only, and where a
   catalog has no photo-z, those buckets are empty rather than backfilled
   with stellar RV.
4. **No SED / spectrum-summary interpretation of `distributions`.** No
   Gaia BP/RP spectra or summary spectra. Companion tables stay out of
   scope.
5. **Single photometry mode per catalog.** DES Y6 Gold and DELVE DR3 Gold
   ship `wavg_mag_psf_*`; SkyMapper DR4 ships `*_psf` (only family
   available); Gaia ships `phot_*_mean_mag`. AUTO/BDF families are not
   included.
6. **Reddening not shipped.** `ebv_sfd98` is not included even where
   catalogs publish it. Consumers compute extinction from coordinates if
   needed.
7. **Quality flags as baseline.** Catalog-level quality / footprint flags
   are in the core payload; per-band variants are not.
8. **Lowercase column names.** All payload column names are lowercased
   regardless of upstream case. Catalog-native semantics preserved.
9. **Avro payload with downcasted floats.** Coordinates kept as `double`;
   most other floats downcast to `float`. See §9.

---

## 8. Per-catalog core column proposals

The lists below are the proposed core payload per keyword for each catalog.
Any column unavailable in a given catalog is marked as such — we do not
synthesize a substitute.

### 8.1 Gaia DR3 — `gaia_dr3`

Source table: `gaia_source` (DR3 main source). Gaia is point-source by
design; no galaxy shape, no photo-z in the main table. Magnitudes are in
the **Vega** system.

- **brightness** — `phot_g_mean_mag`, `phot_bp_mean_mag`,
  `phot_rp_mean_mag`, `phot_g_mean_flux_over_error`,
  `phot_bp_mean_flux_over_error`, `phot_rp_mean_flux_over_error`. Gaia
  does not publish per-band magnitude errors directly; consumers can
  derive `mag_err ≈ 1.0857 / flux_over_error`.
- **location** — `ra`, `dec`, `ra_error`, `dec_error`, `parallax`,
  `parallax_error`, `pmra`, `pmra_error`, `pmdec`, `pmdec_error`,
  `ref_epoch`
- **shape** — _none. Gaia is point-source by design._
- **distributions / redshift** — _none in the core payload. No photo-z
  in the main HATS catalog; stellar `radial_velocity` is excluded (see
  §6.1)._
- **classification** — `classprob_dsc_combmod_star`,
  `classprob_dsc_combmod_galaxy`, `classprob_dsc_combmod_quasar` (Discrete
  Source Classifier combined-mode probabilities)
- **quality** — `ruwe`, `astrometric_excess_noise`,
  `astrometric_excess_noise_sig` (Gaia astrometric goodness-of-fit; usual
  cuts are `ruwe < 1.4`, `astrometric_excess_noise_sig < 2`)

### 8.2 DES Y6 Gold — `des_y6_gold`

Five bands (g, r, i, z, Y). DECam pipeline; BDF fit, no metacal in this
LSDB variant. DNF photo-z available. Magnitudes are in the **AB** system.

- **brightness** — `wavg_mag_psf_g`, `wavg_mag_psf_r`, `wavg_mag_psf_i`,
  `wavg_mag_psf_z`, `wavg_mag_psf_y`, `wavg_magerr_psf_g`,
  `wavg_magerr_psf_r`, `wavg_magerr_psf_i`, `wavg_magerr_psf_z`,
  `wavg_magerr_psf_y`
- **location** — `ra`, `dec`
- **shape** — `bdf_t`, `bdf_g_1`, `bdf_g_2`, `bdf_fracdev`
- **distributions / redshift** — `dnf_z`, `dnf_zsigma`
- **classification** — `ext_mash` (recommended Y6 Gold star/galaxy
  separator: 0 = star, 4 = galaxy, intermediate values graded)
- **quality** — `flags_gold`, `flags_foreground`, `flags_footprint`,
  `bdf_flags` (catalog-level quality / footprint masks; per-band
  `imaflags_iso_*` not included by default)

### 8.3 DELVE DR3 Gold — `delve_dr3_gold`

Four bands (g, r, i, z) — no Y band. Same DECam pipeline as DES Y6 Gold;
BDF, DNF photo-z, MASH classifier. Magnitudes are in the **AB** system.

- **brightness** — `wavg_mag_psf_g`, `wavg_mag_psf_r`, `wavg_mag_psf_i`,
  `wavg_mag_psf_z`, `wavg_magerr_psf_g`, `wavg_magerr_psf_r`,
  `wavg_magerr_psf_i`, `wavg_magerr_psf_z`
- **location** — `ra`, `dec`
- **shape** — `bdf_t`, `bdf_g_1`, `bdf_g_2`, `bdf_fracdev`
- **distributions / redshift** — `dnf_z`, `dnf_zsigma`
- **classification** — `ext_mash`
- **quality** — `flags_gold`, `flags_foreground`, `flags_footprint`,
  `bdf_flags` (catalog-level quality / footprint masks; per-band
  `imaflags_iso_*` not included by default)

### 8.4 SkyMapper DR4 — `skymapper_dr4`

J2000 suffix on coordinates. Six bands (u, v, g, r, i, z). The LSDB-hosted
DR4 main catalog has **no shape/moment/image-ellipse columns** and **no
photo-z** — only `class_star` for morphological information, and the PSF /
Petrosian / fixed-aperture magnitude families for photometry. Magnitudes
are in the **AB** system.

- **brightness** — `u_psf`, `v_psf`, `g_psf`, `r_psf`, `i_psf`, `z_psf`,
  `e_u_psf`, `e_v_psf`, `e_g_psf`, `e_r_psf`, `e_i_psf`, `e_z_psf`
- **location** — `raj2000`, `dej2000`, `e_raj2000`, `e_dej2000`
- **shape** — _not available in the SkyMapper DR4 main catalog._
- **distributions / redshift** — _not available in the SkyMapper DR4 main
  catalog._
- **classification** — `class_star` (continuous SExtractor classifier; ~1 =
  star, ~0 = galaxy)
- **quality** — `flags`, `nimaflags`, `ngood` (catalog-level quality
  flags; per-band `*_flags`, `*_nimaflags`, `*_ngood` not included by
  default)

*SkyMapper DR4's main catalog provides only PSF photometry — no AUTO/BDF
families exist there.*

---

## 9. Data types in the published payload

The published payload is Avro, matching Hopskotch convention. Avro
supports `float` (32-bit), `double` (64-bit), `int` (32-bit), `long`
(64-bit), `boolean`, and `string` — there is no `float16`.

Most upstream HATS columns are published as `double` or `float`. The
payload downcasts where precision allows, to keep alert sizes manageable
across many per-alert catalog crossmatches. Coordinates keep `double`
because Gaia DR3 is milliarcsec-class and float32's ~7 decimal digits
in degrees is too coarse for that. All other floating-point columns
downcast to `float`.

| Category                                                              | Avro type                          |
| --------------------------------------------------------------------- | ---------------------------------- |
| Coordinates: `ra`, `dec`, `parallax`, `pmra`, `pmdec`, `ref_epoch`    | `double`                           |
| Coordinate / proper-motion / parallax errors                          | `float`                            |
| Magnitudes and magnitude errors                                       | `float`                            |
| Photo-z point estimate and uncertainty                                | `float`                            |
| Classification probabilities and continuous classifier scores         | `float`                            |
| Shape parameters (BDF)                                                | `float`                            |
| Discrete classifier indices (e.g., `ext_mash`)                        | `int`                              |
| Bitmask quality flags                                                 | `int` or `long` (matches upstream) |
| Source identifiers                                                    | `long`                             |

---

## 10. Scope Boundaries

- **Optional / extended payload tier.** Deferred; will be
  revisited after community input on the core.
- **New catalogs.** No additions to the catalog set in this proposal, though
  over time more catalogs will be added to the crossmatch-service.
- **Companion tables.** Gaia BP/RP spectra, QSO/galaxy candidates, DES Y6
  metacal, etc., are not used in this proposal.

---

[gaia-cols]: ../references/gaia_dr3-columns.md
[des-cols]: ../references/des_y6_gold-columns.md
[delve-cols]: ../references/delve_dr3_gold-columns.md
[skymapper-cols]: ../references/skymapper_dr4-columns.md
