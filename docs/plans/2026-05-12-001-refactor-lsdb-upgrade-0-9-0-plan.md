---
title: "refactor: Upgrade LSDB to v0.9.0"
type: refactor
status: active
date: 2026-05-12
origin: docs/brainstorms/2026-05-12-upgrade-lsdb-to-0-9-0-requirements.md
---

# refactor: Upgrade LSDB to v0.9.0

## Summary

Bump the `lsdb` pin from `0.8.1` to `0.9.0` in `crossmatch/requirements.base.txt` and the two `EXTRA_PIP_PACKAGES` lines in `docker/docker-compose.yaml`, in a single atomic commit. No source-code edits — research confirmed `lsdb.open_catalog` and `lsdb.from_dataframe` signatures are byte-identical between 0.8.1 and 0.9.0. Verification is pip resolution, local docker-compose stack startup, the existing Django test suite, the fail-fast Dask version check against the remote cluster, and a single-alert end-to-end smoke run.

---

## Problem Frame

The remote EKS Dask cluster has been upgraded to LSDB 0.9.0; the local crossmatch service and local docker-compose Dask worker still pin `lsdb==0.8.1`. Mismatched LSDB versions across the client (crossmatch service) and the workers (the cluster) risk pickle serialization failures and behavioral drift on catalog objects. Closing the version gap is a precondition for the service running reliably against the upgraded cluster. See origin: `docs/brainstorms/2026-05-12-upgrade-lsdb-to-0-9-0-requirements.md`.

---

## Requirements

- R1. The `lsdb` pin in `crossmatch/requirements.base.txt` is updated from `0.8.1` to `0.9.0` (traces origin R1).
- R2. The `lsdb` version in both `EXTRA_PIP_PACKAGES` lists in `docker/docker-compose.yaml` is updated from `0.8.1` to `0.9.0` (traces origin R2).
- R3. No code edits at the existing LSDB call sites — research verified the relevant 0.9.0 APIs are unchanged from 0.8.1 (traces origin R3; closes as zero-effort — see Key Technical Decisions).
- R4. No new LSDB 0.9.0 APIs or capabilities are adopted (traces origin R4).
- R5. Other pinned packages (numpy, pandas, dask, Python) are not pre-emptively changed; deferred to follow-up PRs if the fail-fast check surfaces a mismatch (traces origin R5).

---

## Scope Boundaries

- Adopting new LSDB 0.9.0 features, APIs, or patterns.
- Modifying the remote EKS Dask cluster's deployment (already on 0.9.0).
- Pre-emptive bumps of numpy / pandas / dask / Python pins.
- Refactoring code in `crossmatch/matching/` or `crossmatch/tasks/` (zero edits required, per research).
- Adding `lsdb` to `_VERSION_CHECK_PACKAGES` in `crossmatch/core/dask.py`.
- Explicitly pinning `hats` in `crossmatch/requirements.base.txt` — let pip pull it transitively per LSDB 0.9.0's `hats>=0.9.0,<0.10` constraint.
- Adding test coverage at the LSDB call sites — known coverage gap, out of scope for this PR.
- Strict byte-for-byte regression testing of crossmatch output against 0.8.1.

---

## Context & Research

### Relevant Code and Patterns

- `crossmatch/requirements.base.txt` — base Python pin list; `lsdb==0.8.1` is on line 12.
- `docker/docker-compose.yaml` lines 353 and 372 — `EXTRA_PIP_PACKAGES: "lsdb==0.8.1 numpy==2.4.2 pandas==2.3.3 s3fs"` on the local `dask-scheduler` and `dask-worker` services. Both lines are identical and must move together.
- `crossmatch/matching/catalog.py` — calls `lsdb.open_catalog(url, ...)` for the hosted HATS catalogs with a module-level cache. **No edits in this PR.**
- `crossmatch/tasks/crossmatch.py` — calls `lsdb.from_dataframe(df, ...)` to wrap alert batches. **No edits in this PR.**
- `crossmatch/core/dask.py` — `_VERSION_CHECK_PACKAGES` tuple at lines 40-50 controls the fail-fast Dask version check; `lsdb` is intentionally not in the tuple. **No edits in this PR.**

### Institutional Learnings

- `docs/solutions/` does not exist in this repo; no codified institutional learnings to inherit.

### External References

- **LSDB v0.9.0 release notes** (`https://github.com/astronomy-commons/lsdb/releases/tag/v0.9.0`) — highlights: `crossmatch_nested(how: 'left' | 'inner')`, progress-bar additions, `to_hats` resume, hats dependency bump. No breaking changes called out by maintainers.
- **LSDB v0.8.2 release notes** (`https://github.com/astronomy-commons/lsdb/releases/tag/v0.8.2`) — intermediate release; default zstd compression for `write_catalog` (irrelevant here — we only read). No breaking changes called out.
- **LSDB v0.9.0 source verification** — `read_hats.py` and `from_dataframe.py` signatures byte-identical to v0.8.1 (confirmed by direct file diff at the tagged refs).
- **LSDB v0.9.0 `pyproject.toml`** — direct constraints: `requires-python>=3.11`, `dask[complete]>=2025.3.0`, `hats>=0.9.0,<0.10`, `nested-pandas>=0.6.7,<0.7.0`, `scipy>=1.7.2`. `numpy` and `pandas` are not pinned by LSDB directly.

---

## Key Technical Decisions

- **R3 closes as zero-effort.** Both call sites in this repo (`lsdb.open_catalog` and `lsdb.from_dataframe`) have byte-identical signatures and return types in v0.9.0 compared to v0.8.1. The "minimum code edits to preserve current behavior" the brainstorm asked for amounts to zero edits. No source-file changes are part of this plan.

- **One atomic commit, not two.** The `crossmatch/requirements.base.txt` pin update and the `docker/docker-compose.yaml` `EXTRA_PIP_PACKAGES` updates land together. Splitting would leave a transient state where one side has lsdb 0.9.0 and the other has 0.8.1; the local docker-compose stack would trip its own fail-fast check between commits.

- **Do not pin `hats` explicitly.** LSDB 0.9.0's transitive constraint `hats>=0.9.0,<0.10` is the right source of truth. Adding a direct `hats` line in `requirements.base.txt` creates a second place to maintain and conflicts on the next LSDB bump.

- **Smoke run carries the verification weight, not the test suite.** The repo has thin test coverage at the LSDB call sites (`crossmatch/brokers/pittgoogle/tests.py` is the only `tests.py` module touching LSDB-adjacent code; there are no tests for `matching/catalog.py` or `tasks/crossmatch.py`). The success criterion "tests pass" is necessary but not sufficient; the single-alert end-to-end smoke run is the actual validation that LSDB-related behavior is preserved.

---

## Open Questions

### Resolved During Planning

- **Do LSDB 0.9.0's `open_catalog` and `from_dataframe` signatures or behaviors differ from 0.8.1?** Resolved: No. Verified by direct comparison of source files at v0.8.1 and v0.9.0 tags. (Closes origin's first deferred question.)
- **Does LSDB 0.9.0 directly force a numpy / pandas / dask / Python bump?** Resolved: No direct LSDB constraint conflicts with current pins. `dask>=2025.3.0` is satisfied by `dask==2026.1.2`; `requires-python>=3.11` matches the existing Dockerfile Python (verify at first container build). numpy and pandas are not pinned by LSDB directly. (Partially closes origin's second deferred question — transitive constraints remain to be verified at install time.)

### Deferred to Implementation

- **Do the transitive constraints (`nested-pandas<0.7.0`, `hats<0.10`) accept the current `numpy==2.4.2` / `pandas==2.3.3`?** The pip resolver during the first container build (or a `pip install --dry-run`) is the definitive test. Answered during U1's verification step.
- **If the fail-fast Dask version check surfaces additional package mismatches against the upgraded remote cluster at first deploy, which packages does it flag?** Answered at deploy time; drives the scope of follow-up PRs. (Closes origin's third deferred question.)

---

## Implementation Units

### U1. Bump LSDB pin to 0.9.0 in all pin locations

**Goal:** Realign the local crossmatch app and the local docker-compose Dask scheduler/worker to the LSDB version already deployed on the remote EKS cluster.

**Requirements:** R1, R2, R3 (closed as zero-effort), R4, R5.

**Dependencies:** None.

**Files:**
- Modify: `crossmatch/requirements.base.txt` (change the `lsdb==0.8.1` line to `lsdb==0.9.0`).
- Modify: `docker/docker-compose.yaml` (both `EXTRA_PIP_PACKAGES` lines — currently `"lsdb==0.8.1 numpy==2.4.2 pandas==2.3.3 s3fs"` on lines 353 and 372 — change each to use `lsdb==0.9.0`).

**Approach:**
- Single edit pass across both files, single commit.
- Do NOT touch `crossmatch/matching/catalog.py`, `crossmatch/tasks/crossmatch.py`, `crossmatch/core/dask.py`, or any other source file. Research confirmed the relevant LSDB APIs are unchanged from 0.8.1.
- Do NOT add a direct `hats` pin; let LSDB 0.9.0's transitive constraint resolve it.

**Patterns to follow:**
- Existing pin style in `crossmatch/requirements.base.txt` — exact `==` pinning, one package per line.
- Existing `EXTRA_PIP_PACKAGES` shape in `docker/docker-compose.yaml` — single-quoted string with space-separated `pkg==version` items.

**Test scenarios:**
- Test expectation: none — pure dependency version change with no source-code edits. The repo's existing Django test surface (the `tests.py` modules under `crossmatch/`) is not extended by this PR.

**Verification:**
- Pip dependency resolution succeeds against the new pin — no version conflicts from `nested-pandas`, `hats`, or any other transitive against the existing `numpy==2.4.2` and `pandas==2.3.3` pins.
- The local docker-compose `dask-scheduler` and `dask-worker` containers come up cleanly with the updated `EXTRA_PIP_PACKAGES` — both reach the running state and accept connections; no pip-install errors in container logs.
- The existing Django test suite passes against the new pin — no regressions. (Necessary but not sufficient — see Key Technical Decisions.)
- A celery worker starts cleanly against the remote EKS Dask cluster (`DASK_SCHEDULER_ADDRESS` set) — the fail-fast Dask version check at `crossmatch/core/dask.py` reports all compared packages (Python, distributed, dask, msgpack, cloudpickle, toolz, tornado, numpy, pandas) aligned; no CrashLoopBackOff.
- One representative alert from each configured broker (Lasair, Pitt-Google, ANTARES) flows end-to-end through crossmatch and produces sensible output against the hosted HATS catalogs (DES Y6 Gold, DELVE DR3 Gold, SkyMapper DR4). Sensible = matches are returned, no errors in worker logs, no pickle exceptions on the wire.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Transitive deps (`nested-pandas`, `hats`) reject current `numpy==2.4.2` / `pandas==2.3.3` at install time | Verification step runs pip resolution first; if it fails, scope expands in a follow-up PR to bump the offending transitive constraint(s). The fail-fast Dask version check already covers numpy/pandas alignment with the cluster. |
| Hosted HATS catalog format incompatibility with LSDB 0.9.0's reader | Smoke run against all three configured catalogs (DES Y6 Gold, DELVE DR3 Gold, SkyMapper DR4) catches this at verification. If it surfaces, surface as a separate issue rather than absorbing silently. |
| Remote EKS cluster is on a slightly different LSDB version than reported (e.g., `0.9.0.post1`, `0.9.1`) | Single-alert smoke run is the only detection mechanism, since the fail-fast check does not compare `lsdb`. Acknowledged limitation; extending the check is explicitly out of scope. |

---

## Sources & References

- **Origin document:** `docs/brainstorms/2026-05-12-upgrade-lsdb-to-0-9-0-requirements.md`
- Related code: `crossmatch/requirements.base.txt`, `docker/docker-compose.yaml`, `crossmatch/matching/catalog.py`, `crossmatch/tasks/crossmatch.py`, `crossmatch/core/dask.py`
- Related prior work: `docs/brainstorms/2026-04-20-fail-fast-dask-version-check-requirements.md` (the fail-fast check that enforces local/cluster alignment); `docs/brainstorms/2026-03-16-pin-python-and-deps-for-dask-cluster-brainstorm.md` (the pinning policy this work participates in).
- External: LSDB v0.9.0 release notes (`https://github.com/astronomy-commons/lsdb/releases/tag/v0.9.0`), LSDB v0.8.2 release notes (`https://github.com/astronomy-commons/lsdb/releases/tag/v0.8.2`), LSDB v0.9.0 `pyproject.toml` at tag.
