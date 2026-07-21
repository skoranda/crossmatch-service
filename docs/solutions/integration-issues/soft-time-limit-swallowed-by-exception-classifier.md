---
title: "Celery soft time limit silently swallowed by the transient-read exception classifier"
date: 2026-07-21
category: docs/solutions/integration-issues/
module: crossmatch/tasks, crossmatch/matching
problem_type: integration_issue
component: background_job
symptoms:
  - "A `crossmatch_batch` that overran its `soft_time_limit` did not revert its alerts to INGESTED; they stayed QUEUED"
  - "The fast soft-limit self-heal silently never fired; recovery fell back to the hard SIGKILL + stuck-timer path"
  - "No error was surfaced -- `SoftTimeLimitExceeded` had been 'handled' (retried / skipped / dropped), so nothing logged a failure"
  - "`is_transient_read_error` / `_transient_read_signature` matched a transient signature on a chain whose outer exception was actually `SoftTimeLimitExceeded`"
root_cause: logic_error
resolution_type: code_fix
severity: high
related_components: [tooling]
tags: [celery, soft-time-limit, exception-handling, exception-chaining, crossmatch, error-classification]
---

# Celery soft time limit silently swallowed by the transient-read exception classifier

## Problem

Adding a Celery per-task soft time limit to `crossmatch_batch` to self-heal
overrunning batches introduced a silent-swallow bug: the `SoftTimeLimitExceeded`
the soft limit raises was caught and misclassified by the task's existing broad
and message-based exception handlers, so the intended revert-to-INGESTED
self-heal never ran. Recovery silently degraded to the slower hard-limit SIGKILL
plus stuck-timer reclaim path.

## Symptoms

- A batch that overran its soft time limit did **not** revert its alerts to
  `INGESTED` for re-dispatch. The alerts stayed `QUEUED`.
- Instead of the fast soft-limit self-heal, recovery fell back to the hard
  `time_limit` SIGKILL backstop and then the stuck-timer reclaim
  (`CROSSMATCH_BATCH_STUCK_SECONDS`), turning a bounded self-revert into a
  multi-minute stall.
- The failure was hard to notice because there was **no error surfaced**: the
  `SoftTimeLimitExceeded` had been "handled" — retried in `_read_with_retry`,
  skipped in the per-catalog handler, or dropped in the per-row loop — so nothing
  logged it as a failure. The self-heal simply, silently, never fired.

## Root cause

`celery.exceptions.SoftTimeLimitExceeded` subclasses `Exception`, so every broad
`except Exception` in the task's call tree catches it. Worse, the crossmatch code
classifies read failures **by message text / class name walked across the
exception chain**, not by type. `is_transient_read_error(exc)` (in
`crossmatch/matching/catalog.py:63`) delegates to `_transient_read_signature`
(`crossmatch/matching/catalog.py:40`), which walks `cur.__cause__ or
cur.__context__` (`crossmatch/matching/catalog.py:59`) and matches each link's
`f'{type(cur).__name__}: {cur}'` against `_TRANSIENT_READ_SIGNATURES`
(`crossmatch/matching/catalog.py:29`). This design exists on purpose: it lets the
raw aiohttp disconnect and fsspec's confusing `TypeError`-wrapped form both
resolve to the underlying transient signature (see the module docstring at
`crossmatch/matching/catalog.py:13` and the two related docs below).

The soft limit can fire *while a transient read error is being handled* — inside
`_read_with_retry`'s retry loop, or inside `.compute()` while lsdb/fsspec is
already handling a disconnect. When it does, Python implicitly chains the
in-flight transient onto `SoftTimeLimitExceeded.__context__`. The message-based
classifier then walks that chain, matches the transient's name, and concludes the
`SoftTimeLimitExceeded` is a retryable/skippable transient:

- in `_read_with_retry` it gets **retried** (`crossmatch/matching/catalog.py:94`),
- in the per-catalog handler it gets **skipped** as a flaky catalog
  (`crossmatch/tasks/crossmatch.py:118`),
- and in the per-row build loop the bare `except Exception: continue`
  (`crossmatch/tasks/crossmatch.py:190`) swallows it outright with no chain needed
  at all.

In every case the exception never reaches the outer `except Exception` that
reverts alerts to `INGESTED` and re-raises (`crossmatch/tasks/crossmatch.py:247`).

## What didn't work

- **Guarding only the task-level handlers.** The first fix added the type-guard to
  the per-catalog handler and the per-row loop in `crossmatch/tasks/crossmatch.py`, but left
  the retry wrapper one layer down untouched. Code review found the identical
  chained-swallow still reachable inside `_read_with_retry`: the soft limit could
  fire during `read_fn()` (the catalog open + `.compute()`), chain a transient via
  `__context__`, and be absorbed as a retry before it ever propagated up to the
  task. The guard had to be pushed down into the helper too.
- **Relying on a bare `SoftTimeLimitExceeded` not matching the classifier.** It is
  true that a *bare* `SoftTimeLimitExceeded` matches none of the transient
  signatures, so in isolation the classifier returns `None`. But that guarantee
  evaporates the moment `__context__` chaining occurs — a *chained*
  `SoftTimeLimitExceeded` carries a matching transient one link down and is
  classified as transient. The class-name/message match on the chain is exactly
  what makes the bare-exception reasoning unsafe.

## Solution

Guard `SoftTimeLimitExceeded` **by type** and re-raise it, placing the guard
**before** every broad `except Exception` and before any message/chain-based
classification, in all three places. Type-matching short-circuits ahead of the
chain-walking classifier.

Per-catalog handler (`crossmatch/tasks/crossmatch.py:93`):

```python
try:
    result_df = crossmatch_alerts(alerts_catalog, catalog_config)
except SoftTimeLimitExceeded:
    raise  # type-guard FIRST: never let the classifier below see it
except Exception as exc:
    if isinstance(exc, RuntimeError) and "Catalogs do not overlap" in str(exc):
        ...
        continue
    if not is_transient_read_error(exc):   # chain-walking classifier
        raise
    ...  # skip catalog
    continue
```

Per-row build loop (`crossmatch/tasks/crossmatch.py:185`):

```python
except SoftTimeLimitExceeded:
    raise  # re-raise so the outer handler reverts to INGESTED
except Exception:
    logger.exception('Skipping unbuildable match row', catalog=catalog_name)
    continue
```

Retry wrapper (`crossmatch/matching/catalog.py:87`):

```python
try:
    return read_fn()
except SoftTimeLimitExceeded:
    raise  # not a retryable read error; propagate
except Exception as exc:
    signature = _transient_read_signature(exc)   # message/chain classifier
    if attempt < attempts and signature is not None:
        ...  # retry
        continue
    raise
```

Order matters in each block: because `except` clauses are tried top-to-bottom and
`SoftTimeLimitExceeded` is a subclass of `Exception`, the type-guard must precede
the broad `except Exception` (and the classification inside it) or it never gets a
chance to match.

Shipped in v0.8.0 (origin PR #20, "auto-recover fast after a worker is
hard-killed mid-batch", merged upstream). The per-catalog guard and the
`_read_with_retry` guard landed in review-fix commits within that PR, after the
initial fix covered only the task-level handlers.

## Why this works

`SoftTimeLimitExceeded` is a **control-flow** exception that happens to subclass
`Exception`. A message/chain-based classifier fundamentally cannot distinguish it
from a genuine transient once `__context__` chaining has occurred, because the
classifier's whole purpose is to look *through* wrappers to a transient signature
buried in the chain — and a soft limit that fired mid-disconnect carries exactly
such a signature one link down. Matching by **type** at the top of the handler
resolves the exception on its own identity before any chain is inspected, so the
classifier never runs against it. Type identity is unambiguous where message/chain
inspection is not.

## Prevention

- When adding **any** Celery soft or hard time limit to a task, audit **every**
  `except Exception` in that task's entire call tree — not just the task body, but
  helpers it calls (retry wrappers, read/compute shims, per-row loops) — and
  re-raise `SoftTimeLimitExceeded` by type as the first `except` clause. This
  matters most anywhere classification is done by message text or by walking
  `__cause__`/`__context__`, because chaining will otherwise disguise the soft
  limit as whatever was in flight.
- Add a regression test that raises `SoftTimeLimitExceeded` **chained from a
  representative transient** and asserts it propagates (reverts / is not
  retried), not merely a bare-exception test. The bare case passes even with the
  bug present; only the chained case exercises it.

Regression tests covering this:

- `crossmatch/tests/test_crossmatch_time_limit.py:86`
  (`test_soft_limit_chained_from_transient_not_skipped`) — raises
  `SoftTimeLimitExceeded` chained from a `RuntimeError("ServerDisconnectedError:
  ...")` and asserts the alert reverts to `INGESTED` rather than the catalog being
  skipped.
- `crossmatch/tests/test_crossmatch_time_limit.py:110`
  (`test_soft_limit_during_row_build_not_swallowed`) — raises the soft limit from
  inside per-row payload build and asserts the per-row `except Exception:
  continue` does not swallow it (alert reverts, nothing published).
- `crossmatch/tests/test_catalog_read_retry.py:131`
  (`test_soft_time_limit_is_not_retried`) — inside `_read_with_retry`, raises the
  soft limit chained from a fake `ServerDisconnectedError` and asserts it
  propagates on the first attempt (`calls["n"] == 1`) instead of being retried.

## Related Issues

- [Transient data.lsdb.io disconnects surface as a cryptic fsspec TypeError](hats-catalog-read-transient-disconnect-fsspec-typeerror.md)
  — introduces the exact classifier this bug exploits: `is_transient_read_error` /
  `_transient_read_signature` walking `__cause__`/`__context__` and matching
  `_TRANSIENT_READ_SIGNATURES` by class-name/message. This bug is the flip side:
  that same chain-walk incidentally catches a *chained* `SoftTimeLimitExceeded`.
- [A flaky data.lsdb.io read surfaces as FileNotFoundError for a file that exists](hats-catalog-read-flaky-endpoint-filenotfounderror.md)
  — adds `FileNotFoundError` to the same signature list via the same
  `_read_with_retry` mechanism. A reminder that broadening the chain-walk match to
  catch more transients can also catch control-flow exceptions like this one; a
  type-guard ahead of the classifier is what keeps the two apart.
