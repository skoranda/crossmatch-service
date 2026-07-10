---
title: "A flaky data.lsdb.io read surfaces as FileNotFoundError for a file that exists, and stalls the whole pipeline"
date: 2026-07-10
category: docs/solutions/integration-issues/
module: crossmatch/matching
problem_type: integration_issue
component: background_job
symptoms:
  - "`Crossmatch failed for catalog` for des_y6_gold, then `Crossmatch batch failed, reverting to INGESTED`, repeating every few minutes"
  - "`FileNotFoundError: https://data.lsdb.io/hats/des/des_y6_gold/.../Npix=4351.parquet?columns=...` raised from matches.compute()"
  - "No batch completes and no notifications are emitted; newest_match stops advancing (visible as a flat Grafana dashboard)"
  - "A direct GET of the exact failing parquet URL returns HTTP 200 — the file is present, just served slowly (1.5-9s per request)"
root_cause: missing_workflow_step
resolution_type: code_fix
severity: high
related_components: [tooling]
tags: [lsdb, hats, fsspec, filenotfounderror, retry, crossmatch, des]
---

# A flaky data.lsdb.io read surfaces as FileNotFoundError for a file that exists, and stalls the whole pipeline

## Problem
The DES / DELVE / SkyMapper HATS catalogs are served over HTTP from
`data.lsdb.io`. When that host is slow and jittery under a large batch's
concurrent parquet range reads, the connection drops mid-read and `fsspec`
re-surfaces the drop as `FileNotFoundError(url)` — for a file that is actually
present. The crossmatch retry helper covered `ServerDisconnectedError` and its
fsspec-wrapped `TypeError` forms (see
[[hats-catalog-read-transient-disconnect-fsspec-typeerror]]) but **not**
`FileNotFoundError`, so this variant raised straight through, failed the batch,
reverted all alerts to INGESTED, re-dispatched, and looped forever with zero
throughput.

## Symptoms
- `Crossmatch failed for catalog catalog=des_y6_gold` immediately followed by
  `Crossmatch batch failed, reverting to INGESTED batch_size=100000`, on a
  ~2-3 minute cycle, never completing.
- The traceback ends in `FileNotFoundError` naming a specific
  `.../Norder=5/Dir=0/Npix=<n>.parquet?columns=...` URL (a different pixel each
  loop, always des_y6_gold).
- `newest_match` (max `CatalogMatch.created_at`) frozen; Grafana shows no
  completed batches and no notifications going out.

## What Didn't Work
- **Reading `FileNotFoundError` literally as a missing file.** The obvious
  reading — the catalog moved, a pixel was deleted, the URL is wrong — is a red
  herring. `curl -I` on the exact failing URL returns **HTTP 200**; the file is
  there. Response times of 1.5-9s per request reveal the real problem: the
  endpoint is slow/flaky, not missing data.
- **Assuming the existing ServerDisconnectedError retry already covered it.**
  The retry fired (its warnings appear in the logs) for the disconnect attempts,
  but a later pixel read raised `FileNotFoundError`, which was not in
  `_TRANSIENT_READ_SIGNATURES`, so `_read_with_retry` re-raised it immediately
  and the batch died.
- **Waiting for it to self-heal.** The flakiness persisted across many batch
  cycles; every batch reached des_y6_gold and failed there, so the pipeline made
  no forward progress on its own.

## Solution
Add `FileNotFoundError` to `_TRANSIENT_READ_SIGNATURES` in
`matching/catalog.py`, so the class-name match in `_is_transient_read_error`
treats it as retryable alongside the aiohttp disconnect family:

```python
_TRANSIENT_READ_SIGNATURES = (
    'ServerDisconnectedError', 'ServerTimeoutError', 'ClientConnectionError',
    'ClientOSError', 'ClientPayloadError', 'ConnectionResetError',
    'FileNotFoundError',
)
```

The retry then re-runs the whole per-catalog read on a fresh connection, which
succeeds once `data.lsdb.io` responds in time.

## Why This Works
The read is failing for a transient transport reason (a dropped/slow HTTP
connection), not because the data is absent — proven by the HTTP 200. Retrying
the read recovers it. Including `FileNotFoundError` is safe because the two
error modes that *should* fail loud do not use this class:
- Requested-column and catalog-schema mistakes are validated up front in
  `_get_catalog` (via `columns="all"` introspection) and raise `ValueError`.
- A genuinely missing file still raises `FileNotFoundError` on every attempt and
  fails loud after the retry budget is exhausted — costing only a little extra
  latency in that rare true-missing case.

## Prevention
- Regression coverage: `crossmatch/tests/test_catalog_read_retry.py` —
  `test_filenotfound_from_flaky_endpoint_is_transient` (a `FileNotFoundError`
  carrying a data.lsdb.io URL is classified transient) and
  `test_retries_filenotfound_then_succeeds` (retried once, then returns).
- When a remote store surfaces a "missing" error, confirm the object actually
  exists (a direct GET) before treating it as a hard/deterministic failure;
  object stores and HTTP caches routinely mislabel transient read failures as
  404 / not-found.
- This only mitigates `data.lsdb.io` flakiness; sustained slowness or errors are
  an upstream host problem to raise with the LSDB data service, not an app bug.
- Note the pipeline-level blast radius: because a single catalog's hard failure
  reverts the *entire* multi-catalog batch (fail-loud design in
  `tasks/crossmatch.py`), one flaky catalog halts all throughput. If flakiness
  recurs, consider making a batch commit the catalogs that succeeded rather than
  discarding them all.

## Related Issues
- Companion to [[hats-catalog-read-transient-disconnect-fsspec-typeerror]] — same
  root theme (transient data.lsdb.io reads), different surfaced error class.
- Fixed on branch `fix/catalog-read-filenotfound-transient`.
- Surfaced while recovering the crossmatch stall whose other cause was the 72h
  stuck-batch threshold (`Alert.queued_at` fix, branch
  `fix/batch-stuck-recovery-queued-at`).
