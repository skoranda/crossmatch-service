---
title: "Transient data.lsdb.io disconnects surface as a cryptic fsspec TypeError, not a network error"
date: 2026-07-10
category: docs/solutions/integration-issues/
module: crossmatch/matching
problem_type: integration_issue
component: background_job
symptoms:
  - "`Crossmatch failed for catalog` logged for skymapper_dr4 / des_y6_gold, failing the crossmatch batch"
  - "`TypeError: can't concat ServerDisconnectedError to bytes` from fsspec/caching.py during matches.compute()"
  - "`TypeError: 'ServerDisconnectedError' object is not subscriptable` (same cause, different fsspec cache path)"
  - "Recurs intermittently across multiple HTTP-served catalogs and both workers; worse under high crossmatch throughput"
root_cause: missing_workflow_step
resolution_type: code_fix
severity: medium
related_components: [tooling]
tags: [lsdb, hats, fsspec, aiohttp, serverdisconnected, retry, crossmatch]
---

# Transient data.lsdb.io disconnects surface as a cryptic fsspec TypeError, not a network error

## Problem
The DES / DELVE / SkyMapper HATS catalogs are served over HTTP from
`data.lsdb.io` (Gaia is on S3). That host intermittently drops the connection
mid parquet byte-range read. The failure surfaces as a confusing `TypeError`
that never mentions the network, and — with no retry on the read — a single
transient blip on one catalog failed the entire multi-catalog crossmatch batch.

## Symptoms
- `Crossmatch failed for catalog` for `skymapper_dr4` and `des_y6_gold` (not
  catalog-specific), on both workers, ~3/6h each, worse right after ingest
  resumed at full throughput.
- The traceback ends in `fsspec/caching.py` at `blocks[-1] += data.pop((start,
  stop))` with `TypeError: can't concat ServerDisconnectedError to bytes`, or in
  a sibling cache path with `TypeError: 'ServerDisconnectedError' object is not
  subscriptable`.

## What Didn't Work
- **Reading the `TypeError` literally.** The message and the top frame point at
  fsspec cache-assembly arithmetic, not at I/O — a red herring. The real error is
  `aiohttp.client_exceptions.ServerDisconnectedError`, which fsspec's parquet
  range cache stored *as the range's data* (instead of bytes) after the fetch
  failed, then blindly concatenated/subscripted later. You only see it by
  reading the exception chain and recognizing the `fsspec.parquet` /
  `open_parquet_file` frames.
- **Treating it as a bad catalog or a SkyMapper-specific issue.** It hit multiple
  HTTP-served catalogs; the common factor is the `data.lsdb.io` HTTP transport,
  not any one catalog's data.
- **Looking for a read-level `retries` knob.** `fsspec` 2026.4.0's
  `HTTPFileSystem` exposes no `retries` kwarg, so there is no clean
  `storage_options` one-liner; resilience has to be added around the read.

## Solution
Wrap the per-catalog read (`open + crossmatch + compute`) in a bounded retry that
fires **only** on the transient network signature and re-raises everything else
immediately, so the fail-loud contract in `tasks/crossmatch.py` is preserved
(bad columns, `"Catalogs do not overlap"`, version skew must still surface).

Match the transient by **class name**, walking `__cause__`/`__context__`, so both
the raw `aiohttp` error and its fsspec-wrapped `TypeError` are caught without
importing aiohttp (`matching/catalog.py`):

```python
_TRANSIENT_READ_SIGNATURES = (
    'ServerDisconnectedError', 'ServerTimeoutError', 'ClientConnectionError',
    'ClientOSError', 'ClientPayloadError', 'ConnectionResetError',
)

def _is_transient_read_error(exc):
    cur = exc
    seen = set()
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if any(s in f'{type(cur).__name__}: {cur}' for s in _TRANSIENT_READ_SIGNATURES):
            return True
        cur = cur.__cause__ or cur.__context__
    return False
```

Attempts and backoff are env-configurable (`CROSSMATCH_READ_RETRIES` default 3,
`CROSSMATCH_READ_RETRY_BACKOFF_SECONDS`). Set retries to 1 to disable.

## Why This Works
The disconnect is transient (a dropped/stale HTTP keep-alive from `data.lsdb.io`,
not a data or logic error), so re-running the read on a fresh connection almost
always succeeds. Retrying only the affected catalog avoids re-running the whole
multi-catalog batch and its DB work. Matching on the class-name string is what
makes the retry robust to fsspec re-wrapping the aiohttp error as a `TypeError`
whose type is useless but whose message still contains `ServerDisconnectedError`.

## Prevention
- Regression coverage: `crossmatch/tests/test_catalog_read_retry.py` — transient
  detection through the wrapping `TypeError` and the cause chain, retry-then-succeed,
  exhaust-then-raise, and deterministic errors (`ValueError`, "Catalogs do not
  overlap") not retried.
- Treat every reused remote connection as droppable and add bounded retry/recycle
  at the boundary. This is the third instance of the same theme this cycle — see
  [[consumer-loop-stale-db-connection]] (Django DB connection recycling) and the
  Cinder/attached-volume recovery in
  [[postgres-disk-full-cinder-volume-expansion-recovery]].
- This only mitigates `data.lsdb.io` flakiness; persistent failure is an upstream
  host problem to raise with the LSDB data service, not an app bug.

## Related Issues
- Fixed in commit on branch `fix/catalog-read-transient-retry`.
- Fail-loud crossmatch design that this retry sits in front of: `tasks/crossmatch.py`.
