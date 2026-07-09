# Brainstorm: Pin Python and Dependencies to Match Dask Cluster

**Date:** 2026-03-16
**Status:** Draft

## What We're Building

Pin Python version and key dependency versions (numpy, pandas, dask) in the crossmatch-service container image to exactly match the Dask scheduler/worker cluster deployed on the dev EKS cluster. This prevents pickle serialization failures when the crossmatch-service eventually connects to the remote Dask scheduler.

## Why This Approach

A colleague deployed a Dask cluster on the dev EKS Kubernetes cluster and discovered that Dask relies heavily on pickle for serialization between client, scheduler, and workers. Version mismatches — particularly in Python, numpy, and pandas — cause deserialization failures. His testing confirmed that a Python 3.12 client with numpy 2.4 and pandas 3 could not communicate with the Python 3.10 cluster.

The crossmatch-service currently uses `python:3.13` as its base image with unpinned dependencies, which resolves to numpy 2.4.3 and pandas 3.0.1 — incompatible with the cluster.

## Key Decisions

### 1. Downgrade Python from 3.13 to 3.10

The Dask cluster runs Python 3.10.19. Pickle compatibility requires matching the Python major.minor version. This is the most impactful change.

**Implication:** Django 6.0 requires Python 3.12+, so Django must also be downgraded.

### 2. Downgrade Django from 6.0 to 5.2 (LTS)

Django 5.2 is the latest version supporting Python 3.10. It is an LTS release (supported until April 2028). The codebase uses no Django 6.0-specific features (verified: no `GeneratedField`, `CompositePrimaryKey`, `LoginRequiredMiddleware`, `db_default`, or async ORM additions).

### 3. Pin numpy==2.2.6 and pandas==2.3.3

Exact match with the cluster versions. These are the packages most likely to cause pickle incompatibilities (confirmed by colleague's testing).

### 4. Full dependency resolution verified

All dependencies in `requirements.base.txt` resolve cleanly with Python 3.10 + Django 5.2.12 + numpy 2.2.6 + pandas 2.3.3:

- LSDB 0.7.3 — works
- dask 2026.1.2 — works
- astropy 6.1.7 — works
- celery 5.6.2 — works
- All other deps — no conflicts

### 5. Dask cluster environment variables (out of scope for now)

The cluster exposes `HOPDEVEL_DASK_SCHEDULER_SERVICE_HOST` and `HOPDEVEL_DASK_SCHEDULER_SERVICE_PORT_TCP_COMM` for connecting to the scheduler. Integrating these into the crossmatch-service (creating a `dask.distributed.Client`) is a separate task to be brainstormed later, after version alignment is in place.

## Changes Required

1. **`docker/Dockerfile`**: Change `python:3.13` to `python:3.10` (both build stages, and the `site-packages` copy path from `python3.13` to `python3.10`).
2. **`crossmatch/requirements.base.txt`**: Change `django>=6.0,<6.1` to `django>=5.2,<5.3`. Add `numpy==2.2.6` and `pandas==2.3.3` pins.
3. **`scimma_crossmatch_service_design.md`**: Update tech stack section to reflect Python 3.10 and Django 5.2.

## Open Questions

1. **What dask version is running on the cluster?** The Dask cluster was built from a container image for Python 3.10. We should pin `dask` and `distributed` to match. Ask colleague for the exact version.

2. **Are there other packages installed on the Dask workers that need alignment?** Beyond numpy, pandas, and Python itself, other packages used in task graphs (e.g., cloudpickle, pyarrow) could also cause pickle issues if mismatched.
