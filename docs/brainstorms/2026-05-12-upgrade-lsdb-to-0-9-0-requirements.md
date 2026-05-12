---
date: 2026-05-12
topic: upgrade-lsdb-to-0-9-0
---

# Upgrade LSDB to v0.9.0

## Summary

Bump the LSDB pin from `0.8.1` to `0.9.0` in this repo's local app and local Dask worker installs, mirroring an upgrade already deployed on the remote EKS Dask cluster. Preserve current behavior; treat this as drop-in maintenance, not a feature adoption opportunity.

---

## Problem Frame

The remote EKS Dask cluster used by the crossmatch service has been upgraded to LSDB 0.9.0. The local crossmatch app and the local docker-compose Dask worker are still pinned at `lsdb==0.8.1`. Mismatched LSDB versions across the client (the crossmatch service) and the workers (the cluster) risk pickle serialization failures and behavioral inconsistencies when catalog objects cross the wire. Closing the version gap is a precondition for the service running reliably against the upgraded cluster.

This work is hygiene, not feature work — the motivation is realignment with deployed infrastructure, not anything new in LSDB 0.9.0.

---

## Requirements

- R1. The `lsdb` pin in the crossmatch service's base Python requirements is updated from `0.8.1` to `0.9.0`.
- R2. The `lsdb` version in every `EXTRA_PIP_PACKAGES` list used by the local docker-compose Dask scheduler and workers is updated from `0.8.1` to `0.9.0`.
- R3. If LSDB 0.9.0 has changed the signatures, return shapes, or behaviors of the existing LSDB call sites in the crossmatch matching and task code, the minimum code edits required to preserve current behavior are made. No broader refactor.
- R4. No new LSDB 0.9.0 APIs or capabilities are adopted as part of this work, even when nicer patterns become available at existing call sites.
- R5. Other pinned packages (numpy, pandas, dask, Python) are not pre-emptively changed in this PR. They move only if either (a) the existing fail-fast Dask version check reports them as mismatched against the cluster after deploy, or (b) LSDB 0.9.0's transitive dependency constraints force them at install time.

---

## Success Criteria

- The existing crossmatch test suite passes against LSDB 0.9.0.
- A celery worker starts cleanly against the upgraded remote Dask cluster — the fail-fast Dask version check reports all compared packages aligned.
- A short manual smoke run against a representative alert batch (e.g., one Lasair, Pitt-Google, or ANTARES alert through end-to-end crossmatch) produces sensible crossmatch output against the hosted HATS catalogs (DES Y6 Gold, DELVE DR3 Gold, SkyMapper DR4).
- The local docker-compose Dask cluster also runs cleanly under the new pin (so local development is not regressed).

---

## Scope Boundaries

- Adopting new LSDB 0.9.0 features, APIs, or patterns.
- Modifying the remote EKS Dask cluster's deployment (already on 0.9.0 by the colleague who operates it).
- Pre-emptive bumps of numpy / pandas / dask / Python pins. If the fail-fast check surfaces a mismatch after deploy, that's a follow-up PR.
- Refactoring of code in `crossmatch/matching/` or `crossmatch/tasks/` beyond what 0.9.0 forces.
- Extending the fail-fast Dask version check to also compare `lsdb` (the current package list does not include it; whether to add it is a separate decision).
- Strict byte-for-byte regression testing of crossmatch output against 0.8.1.

---

## Key Decisions

- **Realign only LSDB in this PR; let the fail-fast check surface other pin drift.** The alternative — auditing the cluster image's full dependency manifest before this PR — was considered and rejected as over-scoped for drop-in maintenance. The fail-fast check is the deliberate safety net for exactly this situation. The check covers Python, distributed, dask, msgpack, cloudpickle, toolz, tornado, numpy, and pandas, so any of those that the cluster bumped alongside LSDB will be reported at worker startup.
- **Preserve current behavior over adoption.** If 0.9.0 introduces nicer APIs at the existing call sites, do not adopt them in this PR. Adoption is a separate brainstorm.
- **LSDB-specific verification is the test suite plus a manual smoke run, not the fail-fast check.** The fail-fast Dask version check does not compare `lsdb` across client and cluster; an LSDB-only mismatch would manifest as runtime pickle or behavior errors, not as a startup-time failure. The combination of unit tests passing and a successful end-to-end smoke run is the intended detection mechanism.

---

## Dependencies / Assumptions

- The remote EKS Dask cluster is currently running LSDB 0.9.0 (user-confirmed; not independently verified in this brainstorm).
- The hosted HATS catalogs at `data.lsdb.io` (DES Y6 Gold, DELVE DR3 Gold, SkyMapper DR4) remain readable by LSDB 0.9.0's catalog loader. If a catalog format break is discovered, that surfaces as a separate issue rather than being silently absorbed in this PR.
- The fail-fast Dask version check's compared-packages list does **not** currently include `lsdb`. Verified at `crossmatch/core/dask.py` (`_VERSION_CHECK_PACKAGES`).

---

## Outstanding Questions

### Deferred to Planning

- [Affects R3][Technical] Do LSDB 0.9.0's `open_catalog` and `from_dataframe` signatures, return shapes, or runtime behaviors differ from 0.8.1 in ways that affect the existing call sites? (Answer by reading the LSDB 0.9.0 release notes / changelog and running the test suite during planning or implementation.)
- [Affects R5][Technical] Does LSDB 0.9.0 impose transitive constraints (e.g., a minimum numpy, pandas, or dask version) that force a pin bump beyond just the `lsdb` line at install time? (Answer by running `pip install lsdb==0.9.0` against the current pin set during planning or first CI run.)
- [Affects R5][Technical] If the fail-fast Dask version check surfaces additional mismatches against the upgraded cluster after deploy, which packages does it flag? (Answered at deploy time; drives the scope of follow-up PRs.)
