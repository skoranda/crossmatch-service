---
title: "Atomic multi-site dependency pinning for cluster-aligned package upgrades"
date: 2026-05-12
category: docs/solutions/conventions/
module: dependency_management
problem_type: convention
component: development_workflow
severity: medium
applies_when:
  - Upgrading any Python package pinned in requirements.base.txt / requirements.lock and docker-compose.yaml EXTRA_PIP_PACKAGES
  - Realigning local docker-compose Dask pins with the remote EKS Dask cluster
  - Performing a drop-in maintenance bump where no source-code API changes are expected
  - Upgrading a package outside the fail-fast Dask version check coverage (e.g., lsdb)
related_components: [tooling, testing_framework]
tags: [dependency-management, dask-cluster, docker-compose, lsdb, version-pinning]
---

# Atomic multi-site dependency pinning for cluster-aligned package upgrades

## Context

The crossmatch service pins dependency versions in four places: the application requirements file (`requirements.base.txt`), the compiled lockfile (`crossmatch/requirements.lock`, which the runtime image is actually built from), and the `EXTRA_PIP_PACKAGES` environment variable on each of the two local docker-compose Dask services (scheduler and worker). This spread of pin sites exists because the runtime image and the local docker-compose scheduler/worker containers must all carry the same package set as the application layer, AND the service connects to a remote EKS Dask cluster operated independently by a colleague whose package environment changes out-of-band.

A fail-fast Dask version check at celery worker startup (`crossmatch/core/dask.py`, `_VERSION_CHECK_PACKAGES`) compares a curated list of serialization-critical packages between the local client and the connected scheduler/workers — but it does not cover every dependency. Notably, it does not cover `lsdb`. This combination — scattered pin sites, a remote cluster whose state changes out-of-band, and a version check with deliberate scope limits — creates a specific failure mode: a developer who doesn't know all four pin sites exist, or who updates them in separate commits, will either leave the local stack in a transiently broken state, ship an image built from a lockfile that drifted from the declared pins, or leave drift undetected until a runtime smoke run exercises it.

## Guidance

1. **Know the four pin sites and update them atomically.** The four locations that must move together in a single commit are:
   - `crossmatch/requirements.base.txt` — the application-layer pip pin (the human-edited source of truth).
   - `crossmatch/requirements.lock` — the compiled lockfile, regenerated from the base file with `pip-compile --strip-extras --output-file=requirements.lock requirements.base.txt`. **The runtime image is built from this file** — `docker/Dockerfile` installs `requirements.lock`, not `requirements.base.txt` — and a lock that drifts from the base file fails a dedicated lock-drift CI check, so it must be regenerated in the same commit as any base-pin change.
   - `docker/docker-compose.yaml`, `dask-scheduler` service, `EXTRA_PIP_PACKAGES` string — the local scheduler container pin.
   - `docker/docker-compose.yaml`, `dask-worker` service, `EXTRA_PIP_PACKAGES` string — the local worker container pin.

   Splitting these across commits is unsafe: the local docker-compose stack's fail-fast version check fires at celery worker startup against whichever pins are currently in tree, so a commit that updates the application pin but not the container pins (or vice versa) will trip the check and fail until the remaining sites are updated.

2. **Understand what the fail-fast check covers and what it deliberately omits.** `_VERSION_CHECK_PACKAGES` in `crossmatch/core/dask.py` currently compares: `python`, `distributed`, `dask`, `msgpack`, `cloudpickle`, `toolz`, `tornado`, `numpy`, `pandas`. It does not include packages like `lsdb` that sit above the Dask serialization boundary. Version drift in unchecked packages will not surface at worker startup — only a runtime smoke run will reveal it. Before upgrading any package, determine whether it falls inside or outside the fail-fast scope; that decision drives how much weight the smoke run carries.

3. **Follow the verification path in order, and treat the smoke run as load-bearing.**
   1. Confirm pip can resolve the new pin without conflict. Run inside Python 3.12 — a venv or a container. Host Python 3.10 fails pip resolution because `django>=6.0,<6.1` in `crossmatch/requirements.base.txt` requires Python 3.12+.
   2. Start the local docker-compose Dask stack (scheduler + worker) and confirm clean startup with no version-check failures.
   3. Run the pytest suite (`python -m pytest`, in-container per `docs/developer.md`) as a low-cost sanity check, but do not treat a clean result as meaningful signal for *dependency alignment* — the unit tests exercise app logic, not the remote Dask serialization round-trip, so the smoke run (step 5) is what actually catches version drift.
   4. Start a celery worker against the remote EKS cluster and confirm the fail-fast check reports all compared packages aligned.
   5. Run a single-alert end-to-end smoke run against the hosted HATS catalogs. This is the only verification surface that exercises the full round-trip including any packages outside the fail-fast scope.

4. **Determine whether source-code edits are needed before touching the pins.** For drop-in maintenance bumps (patch or minor releases with no API changes), check the upstream release notes and diff the call sites in this repo. The two `lsdb` call sites today are `crossmatch/matching/catalog.py` (`lsdb.open_catalog`) and `crossmatch/tasks/crossmatch.py` (`lsdb.from_dataframe`). If the public signatures those call sites use are unchanged, the upgrade is a pure pin bump with no code edits. If signatures or behaviors changed, plan source edits alongside the pin bump and note the scope expansion in the commit message.

## Why This Matters

If pins are updated non-atomically, the fail-fast version check fails between commits and blocks any developer who pulls mid-upgrade — the local docker-compose stack will refuse to start until the remaining pin sites catch up.

If pins are updated in the wrong subset of the four sites, the application layer and the container layer diverge, producing confusing behavior where the containers run a different version than the application expects.

If `requirements.base.txt` moves but `crossmatch/requirements.lock` is not regenerated, two things go wrong: the lock-drift CI check fails the branch, and — because `docker/Dockerfile` installs from the lock — the built runtime image silently lags the declared pins until the lock is recompiled. Regenerate the lock in the same commit.

For packages outside the fail-fast check scope (anything not in `_VERSION_CHECK_PACKAGES`), version drift between the local environment and the remote EKS cluster does not surface at startup — it appears as pickle deserialization errors, unexpected `AttributeError`s, or silent result corruption during actual crossmatch tasks. The smoke run is the only gate that catches this category of problem, which means skipping it leaves the service in an unknown state until production traffic exercises it.

## When to Apply

- When bumping any package that appears in `EXTRA_PIP_PACKAGES` in `docker/docker-compose.yaml`, regardless of whether it is in the fail-fast check scope.
- When upgrading a package whose version must align with the remotely-operated EKS Dask cluster — confirm with the cluster operator that the cluster side has already moved or will move atomically with the local change.
- On drop-in maintenance bumps (no expected API changes) and on bumps that carry breaking API changes alike — the distinction affects whether source-code edits accompany the pin bump, not whether the three-site atomic pattern applies.
- When the remote cluster has already been upgraded and the local pins are lagging (the "catch up" case) — same atomicity requirement.

## Examples

### LSDB 0.8.1 → 0.9.0 upgrade (branch `refactor/lsdb-upgrade-0.9.0`, 2026-05-12)

Three pin sites updated in one atomic commit (this upgrade predates `crossmatch/requirements.lock`; the same bump today would also regenerate the lock, making it four):

- `crossmatch/requirements.base.txt` line 12: `lsdb==0.8.1` → `lsdb==0.9.0`
- `docker/docker-compose.yaml` line 353 (`dask-scheduler` `EXTRA_PIP_PACKAGES`): `"lsdb==0.8.1 numpy==2.4.2 pandas==2.3.3 s3fs"` → `"lsdb==0.9.0 ..."`
- `docker/docker-compose.yaml` line 372 (`dask-worker` `EXTRA_PIP_PACKAGES`): identical string updated

Pre-upgrade research confirmed that `lsdb.open_catalog` and `lsdb.from_dataframe` signatures were byte-identical between v0.8.1 and v0.9.0 (verified against the upstream `https://github.com/astronomy-commons/lsdb` release tags). No edits to `crossmatch/matching/catalog.py` or `crossmatch/tasks/crossmatch.py` were needed.

The `lsdb` package is not in `_VERSION_CHECK_PACKAGES`, so the fail-fast check at celery startup would not have detected drift had the pins been left mismatched. The smoke run against the three hosted HATS catalogs (DES Y6 Gold, DELVE DR3 Gold, SkyMapper DR4) was the gate that confirmed correctness.

Verification outcomes:

1. Pip resolution in a Python 3.12 venv — clean, no conflicts.
2. Local docker-compose stack — scheduler and worker came up cleanly with the updated `EXTRA_PIP_PACKAGES`.
3. `manage.py test` — found zero tests (Django's default runner does not discover this project's suite). **Note: a unit-test result is not load-bearing for a dependency bump.** A real pytest/pytest-django suite now exists under `crossmatch/tests/` and runs in-container (per `docs/developer.md`), but even a green run cannot reveal cluster version drift — the unit tests exercise app logic, not the remote Dask serialization round-trip. The meaningful verification surfaces for an upgrade are the docker-compose startup, the fail-fast Dask check, and the end-to-end smoke run.
4. Celery worker started against the remote EKS cluster — fail-fast check reported all compared packages aligned.
5. Single-alert end-to-end smoke run — returned sensible crossmatch results against all three catalogs with no pickle exceptions.

## Related

- `docs/brainstorms/2026-05-12-upgrade-lsdb-to-0-9-0-requirements.md` — requirements doc that drove the upgrade; states the fail-fast check's lsdb gap and the smoke run's load-bearing role explicitly.
- `docs/plans/2026-05-12-001-refactor-lsdb-upgrade-0-9-0-plan.md` — executed plan; definitive line-numbered record of the three pin sites and the full verification checklist.
- `docs/brainstorms/2026-04-20-fail-fast-dask-version-check-requirements.md` — background on why version drift causes opaque pickle failures.
- `docs/plans/2026-04-20-001-feat-fail-fast-dask-version-check-plan.md` — specifies `_VERSION_CHECK_PACKAGES`, the install-at-startup race that motivates the ≥1-worker wait, and why `lsdb` is intentionally absent from the checked set.
- `docs/brainstorms/2026-03-19-local-dask-scheduler-docker-compose-brainstorm.md` — formalizes `EXTRA_PIP_PACKAGES` as the local Dask worker pin site and explains the rationale (workers need packages for pickle deserialization; the scheduler does not strictly require all of them but carries the same set for symmetry).
- `docs/brainstorms/2026-03-16-pin-python-312-and-deps-for-dask-cluster-brainstorm.md` — introduced `lsdb` as a pinned dependency and established the two-pin-site pattern.
- `crossmatch/core/dask.py` (`_VERSION_CHECK_PACKAGES`) — live code for the fail-fast check; references the intentional absence of `lsdb` here.
