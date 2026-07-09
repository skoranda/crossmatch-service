---
title: Pin Python 3.10 and Dependencies to Match Dask Cluster
type: refactor
status: completed
date: 2026-03-16
origin: docs/brainstorms/2026-03-16-pin-python-and-deps-for-dask-cluster-brainstorm.md
---

# Pin Python 3.10 and Dependencies to Match Dask Cluster

## Overview

Downgrade the crossmatch-service container from Python 3.13 to Python 3.10 and pin numpy/pandas to exactly match the Dask cluster deployed on the dev EKS cluster. This prevents pickle serialization failures when the service connects to the remote Dask scheduler.

Django must also be downgraded from 6.0 to 5.2 LTS because Django 6.0 requires Python 3.12+ (see brainstorm: docs/brainstorms/2026-03-16-pin-python-and-deps-for-dask-cluster-brainstorm.md).

## Acceptance Criteria

- [x] Dockerfile uses `python:3.10` base image (both stages) with correct `python3.10` site-packages path
- [x] `requirements.base.txt` pins `django>=5.2,<5.3`, `numpy==2.2.6`, `pandas==2.3.3`
- [x] Docker image builds successfully with all dependencies resolving
- [ ] All services start cleanly (antares-consumer, lasair-consumer, celery-worker, celery-beat, flower)
- [ ] Existing Django migrations apply without error under Django 5.2
- [ ] Crossmatch pipeline (ingest → batch dispatch → LSDB crossmatch → notifications) works end-to-end
- [x] Design document updated to reflect Python 3.10 and Django 5.2 LTS

## Changes

### 1. `docker/Dockerfile`

Change Python version on 3 lines:

```dockerfile
# Line 1: deps stage base image
FROM python:3.10 AS deps

# Line 6: runtime stage base image
FROM python:3.10

# Line 15: site-packages copy path (both source and destination)
COPY --from=deps /usr/local/lib/python3.10/site-packages/ /usr/local/lib/python3.10/site-packages/
```

### 2. `crossmatch/requirements.base.txt`

```
# Pin to match Dask cluster (Python 3.10.19, see dask.md)
numpy==2.2.6
pandas==2.3.3
django>=5.2,<5.3
```

- Change `django>=6.0,<6.1` → `django>=5.2,<5.3`
- Add `numpy==2.2.6` and `pandas==2.3.3` pins

### 3. `scimma_crossmatch_service_design.md`

- Section 8.1 tech stack: Change `Python 3.11+` → `Python 3.10` and note this is constrained by Dask cluster compatibility
- Section 8.1: Note `Django 5.2 LTS` specifically (not just "Django")

## Open Questions (from brainstorm, unresolved)

1. **Exact dask/distributed version on the cluster** — These are currently unpinned (pulled transitively via lsdb). Once the colleague confirms the cluster versions, pin `dask` and `distributed` explicitly. This is the most important remaining gap for pickle compatibility.

2. **cloudpickle version on the cluster** — Dask uses cloudpickle (not stdlib pickle) for task serialization. Version mismatch here can also cause failures. Should be pinned once cluster version is confirmed.

3. **Whether to pin lsdb itself** — Currently unpinned. lsdb 0.7.3 is verified to work. A future rebuild could pull a newer version that changes Dask task graph structure or drops Python 3.10 support.

## Notes

- **Python 3.10 EOL**: October 2026. This is a compatibility constraint driven by the Dask cluster, not a permanent project choice. When the cluster upgrades, the service should follow.
- **Django 5.2 LTS**: Supported through April 2028. No Django 6.0-specific features are used in the codebase (verified: no `GeneratedField`, `CompositePrimaryKey`, `LoginRequiredMiddleware`, `db_default`).
- **Migration compatibility**: Existing migrations use standard `django.db.models` imports and are compatible with Django 5.2.

## Sources

- **Origin brainstorm:** [docs/brainstorms/2026-03-16-pin-python-and-deps-for-dask-cluster-brainstorm.md](docs/brainstorms/2026-03-16-pin-python-and-deps-for-dask-cluster-brainstorm.md) — Key decisions: Python 3.10, Django 5.2 LTS, exact numpy/pandas pins
- **Colleague's findings:** [dask.md](dask.md) — Cluster versions and pickle compatibility testing
