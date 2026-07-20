---
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-brainstorm
execution: code
type: fix
date: 2026-07-20
---

# DES and DELVE S3 Catalog Access - Plan

## Goal Capsule

- **Objective:** Make DES Y6 Gold and DELVE DR3 Gold crossmatch reads reliable by
  reading them from their public S3 mirrors instead of the degraded
  `data.lsdb.io` HTTPS host, escaping the CDN/origin failures that currently
  block DES crossmatches.
- **Product authority:** Maintainer/developer (Scott Koranda).
- **Spans two repos:** the app repo `crossmatch-service` (config default + local
  dev + app-repo Helm chart) and the gitops repo `crossmatch-service-k8s-gitops`
  (the chart that deploys DEV/PROD). Gitops paths below are prefixed
  `crossmatch-service-k8s-gitops/`.
- **Open blockers:** None. The exact S3 URIs and any `storage_options` need are
  resolved empirically in U1 before config lands.

---

## Product Contract

_Product Contract unchanged by this enrichment — IDs R1-R5, AE1-AE3, KD1-KD3
preserved as written._

### Problem

`data.lsdb.io` (the HTTPS host for DES, DELVE, and SkyMapper HATS catalogs)
degrades under the concurrent multi-partition range-read load of an `lsdb`
crossmatch `.compute()`, returning a varying mix of `ServerDisconnectedError`,
`ConnectionTimeoutError`, and HTTP 502/504. Diagnosed on PROD 2026-07-20:
isolated range GETs to the exact failing files return HTTP 206 with data, so the
files are present and healthy — it is origin/CDN degradation under load, not
missing data. Because one failing catalog aborts the whole crossmatch batch, this
has blocked all DES crossmatches (`MATCHED` frozen, no notifications, no
publications).

Gaia DR3 reads reliably in the same jobs because it is served from a public AWS
S3 bucket (`s3://stpubdata/...`), not `data.lsdb.io`. DES Y6 Gold and DELVE DR3
Gold also have public (anonymous) S3 mirrors; SkyMapper DR4 does not (HTTPS only).
The per-catalog `hats_url` is an env-overridable setting
(`crossmatch/project/settings.py`, `CROSSMATCH_CATALOGS`), so pointing DES and
DELVE at S3 is a configuration change on the same code path Gaia already uses.

### Requirements

- **R1.** DES Y6 Gold and DELVE DR3 Gold are read from their public S3 mirrors
  instead of the `data.lsdb.io` HTTPS endpoints.
- **R2.** S3 access is anonymous/public — no AWS credentials, no new secrets, no
  requester-pays — matching how Gaia is already read.
- **R3.** After the change, DES and DELVE reads succeed under real crossmatch
  concurrent load, without the `ServerDisconnectedError` / `ConnectionTimeoutError`
  / 502 / 504 failures currently seen from those catalogs.
- **R4.** The change moves the catalog URL wherever it is actually set for each
  environment (the settings default and any DEV/PROD env override) so DEV and
  PROD both switch — no environment left silently on HTTPS.
- **R5.** SkyMapper DR4 remains on `data.lsdb.io` HTTPS (no S3 mirror available);
  its residual exposure is explicitly accepted here. Because one failing catalog
  still aborts the whole batch (resilience deferred — see KD3), a SkyMapper
  degradation continues to abort batches and lose the now-reliable DES/DELVE
  matches too. So DES/DELVE reliability is improved *except when SkyMapper
  degrades* — not unconditional.

### Scope Boundaries

**In scope**
- Repointing the DES and DELVE catalog URLs (`DES_HATS_URL`, `DELVE_HATS_URL`) to
  their public S3 URIs.
- Confirming whether any `storage_options` (e.g. `anon=True`, region) are required
  for these buckets, and adjusting the `open_catalog` call only if they are.
- App repo (`crossmatch/project/settings.py`, `docker/`, the app-repo Helm chart)
  plus the gitops chart values that set the `*_HATS_URL` for DEV/PROD.

**Out of scope**
- SkyMapper DR4 — stays on HTTPS by decision.
- Resilience to a single catalog failing (one flaky catalog aborting the whole
  batch) — deferred to a separate future brainstorm; it is what neutralizes
  SkyMapper's residual HTTPS exposure, but it is not this change.
- The mid-batch worker-kill recovery work — separate plan
  `docs/plans/2026-07-20-001-fix-crossmatch-batch-kill-recovery-plan.md`.
- Any change to Gaia (already on S3) or to how matches/notifications are computed
  or published.

### Success Criteria

- **AE1.** With DES and DELVE pointed at S3, a crossmatch batch reads both
  catalogs successfully under real concurrent load and produces matches — no
  `ServerDisconnectedError` / `ConnectionTimeoutError` / 502 / 504 from DES or
  DELVE (when SkyMapper is not concurrently degrading; see R5).
- **AE2.** No AWS credentials or new secrets are introduced; the reads work
  anonymously, the same way Gaia's do.
- **AE3.** Both DEV and PROD read DES and DELVE from S3 after the change (no
  environment left on the HTTPS URL).

### Key Decisions

- **KD1.** Switch DES and DELVE to public S3 mirrors; leave SkyMapper on HTTPS
  (no S3 mirror exists for it). _(session-settled 2026-07-20.)_
- **KD2.** Anonymous/public S3 access only — no credentials, secrets, or
  requester-pays; egress from public AWS Open Data buckets is effectively free and
  already accepted for Gaia. _(session-settled 2026-07-20.)_
- **KD3.** Accept SkyMapper's residual HTTPS exposure for now; the one-flaky-
  catalog-aborts-the-batch resilience that would isolate it is deferred to a
  separate future brainstorm. _(session-settled 2026-07-20.)_

---

## Key Technical Decisions

- **KTD1 (product KD1/KD2, carried down).** Repoint DES + DELVE to their public
  **anonymous** S3 mirrors; SkyMapper stays HTTPS.
  _(session-settled: user-directed — chosen over all-three / DES-only, and over
  credentialed/requester-pays access.)_
- **KTD2 — change the URL at all four config layers, across both repos.** The
  Helm charts render `DES_HATS_URL` from `.Values.crossmatch.des_hats_url`
  (`crossmatch-service-k8s-gitops/apps/crossmatch-service/templates/_helpers.yaml:174-177`
  and `kubernetes/charts/crossmatch-service/templates/_helpers.yaml:133-135`), so
  the deploy-time env var **always overrides** the `settings.py` `os.getenv`
  default. Changing only `settings.py` would not move DEV/PROD. The URL is set in:
  the `settings.py` default, `docker/.env` + `docker-compose.yaml`, the app-repo
  chart values (`kubernetes/charts/.../values.yaml` + `dev-overrides.yaml`), and
  the gitops chart values (`apps/crossmatch-service/values.yaml`). All four move
  together. _(session-settled: user-directed 2026-07-20 — chosen over
  live-path-only, to leave no HTTPS default anywhere.)_
- **KTD3 — resolve the exact URIs and the `storage_options` need empirically,
  first (U1).** The precise `s3://bucket/prefix` is an external lookup, and Gaia
  already reads `s3://stpubdata` anonymously with **no** `storage_options`
  (`crossmatch/matching/catalog.py:132,143`), so the default expectation is that
  DES/DELVE read the same way. Verify against the real mirrors before wiring
  config, rather than assuming. This doubles as the "validate the target mirror
  before PROD" check.
- **KTD4 — add `storage_options` only if U1 proves them necessary.** If the plain
  anonymous read fails, the likely cause is bucket region (not credentials).
  Apply any needed options to **both** `open_catalog` calls
  (`catalog.py:132` introspection and `:143` load) so schema-check and load stay
  consistent; otherwise leave the call unchanged.

---

## Implementation Units

> **Target repos.** Paths without a prefix are in the app repo
> `crossmatch-service`. Paths prefixed `crossmatch-service-k8s-gitops/` are in the
> sibling gitops repo (what ArgoCD deploys). U4 is a deploy/verify step in the
> gitops repo.

### U1. Resolve S3 URIs and smoke-verify anonymous reads

- **Goal:** Determine the precise `s3://bucket/prefix` for the DES Y6 Gold and
  DELVE DR3 Gold public mirrors, and confirm each reads anonymously from the
  cluster — resolving the exact-URI and `storage_options` unknowns before any
  config lands.
- **Requirements:** R1, R2; validates KTD3. (R3 is proven post-change in U4.)
- **Dependencies:** none.
- **Files:** none — discovery + smoke check (run from a cluster worker pod, which
  already reads Gaia from `s3://stpubdata`, or an equivalent venv).
- **Approach:** Get the URIs from the LSDB S3 catalog page
  (`https://data.lsdb.io/DES/DES_Y6_Gold_(US-East,_S3)`) and the LSDB data-access
  docs. From within a worker pod, run `lsdb.open_catalog("<des-s3-uri>",
  columns="all")` and a small representative `.compute()` read for each of DES and
  DELVE. Confirm anonymous access works with no `storage_options`. If a read
  fails, record whether the cause is credentials (needs `anon=True`) or region
  (needs region/`client_kwargs`) — that decides U3.
- **Execution note:** Smoke-verify the real S3 read under a representative
  concurrent read **first**, so the config change lands on a proven URI and a
  known `storage_options` answer.
- **Test expectation:** none — discovery/smoke verification, not a code change.
- **Verification:** both mirrors load their `columns="all"` schema anonymously,
  and a representative read `.compute()`s without `data.lsdb.io`-style disconnects.
  A column-validation failure here signals **schema drift** (the mirror's column
  names/case differ from `docs/references/<catalog>-columns.md`), not a bad URI.

### U2. Point DES and DELVE at S3 across all config layers

- **Goal:** Set the DES/DELVE catalog URL to the U1-verified S3 URIs everywhere the
  value is defined, so no environment or local default remains on HTTPS.
- **Requirements:** R1, R4 (AE3); implements KTD1, KTD2.
- **Dependencies:** U1.
- **Files:**
  - `crossmatch/project/settings.py` — `DES_HATS_URL`, `DELVE_HATS_URL` defaults
  - `docker/.env` — `DES_HATS_URL` (add `DELVE_HATS_URL`)
  - `docker/docker-compose.yaml` — the `DES_HATS_URL` / `DELVE_HATS_URL` `:-` default fallbacks
  - `kubernetes/charts/crossmatch-service/values.yaml` — `crossmatch.des_hats_url`, `crossmatch.delve_hats_url`
  - `kubernetes/dev-overrides.yaml.example` (tracked) — `des_hats_url`, `delve_hats_url`. Note: `kubernetes/dev-overrides.yaml` is gitignored/local-only (edit optional, not committed) and currently carries only `des_hats_url`; add `delve_hats_url` there too if you run it locally.
  - `crossmatch-service-k8s-gitops/apps/crossmatch-service/values.yaml` — `crossmatch.des_hats_url`, `crossmatch.delve_hats_url` (DEV/PROD authoritative)
  - `crossmatch/tests/test_catalog_config.py` — new test
- **Approach:** Replace the two `https://data.lsdb.io/...` values with the S3 URIs
  at each site. Leave Gaia and SkyMapper untouched. The gitops `values.yaml` base
  change reaches DEV (auto-sync) and PROD (via release tag); DEV/PROD overlays do
  not override these keys, so the base is authoritative.
- **Patterns to follow:** mirror the existing Gaia `s3://stpubdata/...` value that
  already sits beside each of these keys.
- **Test scenarios:**
  - `CROSSMATCH_CATALOGS` entry `des_y6_gold` has `hats_url` starting `s3://` and
    not containing `data.lsdb.io`. Covers R1.
  - `CROSSMATCH_CATALOGS` entry `delve_dr3_gold` likewise `s3://`, no
    `data.lsdb.io`. Covers R1.
  - `skymapper_dr4` still points at `data.lsdb.io` (unchanged); `gaia_dr3`
    unchanged. Guards KD1's SkyMapper carve-out and Gaia non-change.
- **Verification:** a repo-wide grep shows no `data.lsdb.io` for DES/DELVE in any
  of the config files listed above (all four layers); the config test passes.

### U3. Add anonymous-S3 `storage_options` — only if U1 requires it (conditional)

- **Goal:** If U1 showed the plain read needs `anon=True` and/or a region, pass
  matching `storage_options` so DES/DELVE read successfully; otherwise this unit is
  a no-op and is recorded as skipped.
- **Requirements:** R2, R3; implements KTD4.
- **Dependencies:** U1, U2.
- **Files:** `crossmatch/matching/catalog.py` (both `open_catalog` calls, ~line
  132 introspection and ~143 load) + `crossmatch/tests/test_catalog_read_retry.py`
  (or a sibling) for coverage.
- **Approach:** Only if needed. Derive `storage_options` for the **DES and DELVE**
  reads (e.g. `{"anon": True}`, plus region `client_kwargs` if U1 showed a region
  mismatch) and pass them to **both** `open_catalog` calls (introspection and
  load). Scope the derivation to DES/DELVE so Gaia's call stays byte-for-byte
  unchanged (Gaia is out of scope). Note the options must reach the **Dask
  workers** that run the distributed `.compute()`, not only the driver's
  introspection — confirm propagation during the U1 smoke under real concurrency.
  If U1 showed no options are needed, skip this unit and note it.
- **Execution note:** Conditional on U1 — implement only if the plain anonymous
  read failed. Gaia's precedent (no `storage_options`) says it likely will not be
  needed.
- **Test scenarios (only if implemented):**
  - The DES and DELVE reads receive `storage_options` containing `anon: True`
    (and region when required); Gaia's call is unchanged and SkyMapper's
    `https://` read gets none. Covers R2.
  - Existing `test_catalog_read_retry.py` cases stay green (the retry wrapper is
    unchanged).
- **Verification:** DES/DELVE and Gaia read anonymously; the existing catalog-read
  tests pass unchanged.

### U4. Switch DEV, verify end-to-end, then promote to PROD

- **Goal:** Deploy the S3 switch to DEV and confirm DES/DELVE crossmatches produce
  matches from S3 under real load, then promote to PROD via the standard tag-pinned
  release process and re-verify.
- **Requirements:** R3, R4 (AE1, AE3); realizes KTD1 in production.
- **Dependencies:** U2 (and U3 if it was needed).
- **Files:** none new — the gitops `apps/crossmatch-service/values.yaml` change
  from U2 is the deployed artifact; this unit is deploy + verification.
- **Approach:** DEV tracks `main` HEAD, so merging the gitops values change
  auto-syncs DEV. Watch a crossmatch batch read DES + DELVE from S3 and produce
  matches with no `ServerDisconnectedError` / `ConnectionTimeoutError` / 502 / 504
  from those catalogs. Then promote to PROD via the tag-pinned release process
  (advance the release tag + bump the workload `targetRevision` — the same
  mechanism as `docs/plans/2026-07-20-001-...`) and re-verify on PROD.
- **Execution note:** Runtime/smoke verification on DEV **before** PROD promotion —
  this is the end-to-end proof of R3/AE1. Do not promote PROD until DEV shows
  DES + DELVE matches flowing from S3.
- **Test expectation:** none — runtime/deployment verification, observed via worker
  logs and match/notification flow, not unit coverage.
- **Verification:** on DEV, a crossmatch batch produces DES + DELVE matches from S3
  with no `data.lsdb.io` errors for those catalogs and `MATCHED` advancing; PROD
  shows the same after promotion.

---

## Verification Contract

- **Anonymous read (U1):** `lsdb.open_catalog(<s3-uri>, columns="all")` succeeds
  for DES and DELVE from a cluster pod with no credentials configured, **and** a
  representative `.compute()` read completes without `data.lsdb.io`-style
  disconnects. (AE2)
- **Config coverage (U2):** no `data.lsdb.io` remains for DES/DELVE in
  `settings.py`, `docker/`, either Helm chart's values, or the gitops values;
  `test_catalog_config.py` green; SkyMapper and Gaia unchanged. (R1, R4)
- **Suite green:** `python -m pytest` passes in-container (per `docs/developer.md`),
  including `crossmatch/tests/test_catalog_read_retry.py`.
- **End-to-end (U4):** a DEV crossmatch batch reads DES + DELVE from S3 and produces
  matches with none of the `ServerDisconnectedError` / `ConnectionTimeoutError` /
  502 / 504 failures for those catalogs; PROD matches this after promotion. (AE1,
  AE3)

## Definition of Done

- DES and DELVE resolve to `s3://` URIs in all four config layers across both
  repos; SkyMapper and Gaia unchanged.
- Anonymous read verified from the cluster; no new secrets or credentials (AE2).
- `storage_options` added only where U1 proved them necessary, applied to both
  `open_catalog` calls (U3), or explicitly recorded as not needed.
- DEV verified end-to-end (DES + DELVE matches from S3 under real load); PROD
  promoted via the release tag and verified (AE1, AE3).
- The existing test suite is green.

## Implementation-Time Unknowns — resolved 2026-07-20

- **Exact S3 URIs — RESOLVED and verified** anonymously from a worker pod:
  DES = `s3://stpubdata/mast/public/des/hats/des_y6_gold` (336 columns),
  DELVE = `s3://stpubdata/mast/public/delve/hats/delve_dr3_gold` (252 columns).
  Key requested columns present (no schema drift); `head()` reads succeeded with
  no `data.lsdb.io`-style disconnects. Both are under `stpubdata` (same bucket as
  Gaia), reached via the nested `mast/public/<survey>/hats/<catalog>` prefix.
- **`storage_options` — RESOLVED: none needed.** Both mirrors read anonymously
  with no `storage_options` (same `stpubdata`/us-east-1 path as Gaia), so **U3 is
  skipped**.

## Sources & Research

- Root cause diagnosed live on PROD this session: files present (HTTP 206 in
  isolation) but concurrent-load CDN degradation on `data.lsdb.io`.
- Codebase grounding: `crossmatch/project/settings.py` (`CROSSMATCH_CATALOGS`,
  `*_HATS_URL` `os.getenv` defaults); `crossmatch/matching/catalog.py`
  (`open_catalog` called twice with no `storage_options`; up-front column
  validation fails loud citing `docs/references/<catalog>-columns.md`, guarding
  mirror schema drift); the four config layers per KTD2.
- Related: `docs/solutions/integration-issues/hats-catalog-read-transient-disconnect-fsspec-typeerror.md`
  (the retry wrapper this change reduces reliance on).
