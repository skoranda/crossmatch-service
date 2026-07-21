---
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-brainstorm
execution: code
type: fix
date: 2026-07-20
---

# Crossmatch Single-Catalog Resilience - Plan

## Goal Capsule

- **Objective:** A single flaky or down catalog no longer aborts the whole
  crossmatch batch. When a catalog's reads persistently fail, the batch skips it
  and finalizes the affected alerts with the catalogs that succeeded (marked
  partial), so the pipeline keeps flowing — provided at least one catalog
  succeeded. A total (zero-success) outage still fails closed and publishes
  nothing.
- **Product authority:** Maintainer/developer (Scott Koranda).
- **Open blockers:** None. Unblocks the live PROD stall (2026-07-20): SkyMapper on
  `data.lsdb.io` is aborting every batch after the DES/DELVE S3 switch, so the
  337k `INGESTED` backlog cannot drain.

---

## Product Contract

_Product Contract unchanged by this enrichment — IDs R1-R6, AE1-AE5, KD1-KD3
preserved as written._

### Problem

`crossmatch_batch` (`crossmatch/tasks/crossmatch.py`) treats a catalog
read/compute error as fatal: it re-raises (the `except Exception: ... raise` at
lines 81-89), and the outer handler reverts the whole batch to `INGESTED` (lines
172-182), rolling back the matches already written for the catalogs that
succeeded. A no-spatial-overlap condition is already handled gracefully (logged,
loop `continue`s, lines 75-79) — only a read *error* aborts. So one persistently-
failing catalog blocks all crossmatching, including the healthy ones.

Observed on PROD 2026-07-20: after DES/DELVE moved to public S3 (plan
`docs/plans/2026-07-20-002-fix-des-delve-s3-catalog-access-plan.md`), batches read
Gaia (63,141), DES (9,756), and DELVE (79,034) from S3 successfully, then failed
on SkyMapper — still on the degraded `data.lsdb.io` — with a
`ServerDisconnectedError`. The whole batch reverted, and the 337k `INGESTED`
backlog now cycles without draining: no matches persist, no notifications publish.

A secondary bug: the retry handler logs
`error="'ServerDisconnectedError' object is not subscriptable"` — a `TypeError`
in how the fsspec-wrapped error is handled. Retries still fire via message-text
matching, but the wrapping is buggy.

### Requirements

- **R1.** A catalog whose reads persistently fail (retries exhausted) is skipped
  for that batch — logged, loop continues — instead of aborting the whole batch.
- **R2.** Alerts in a batch where one or more catalogs were skipped are still
  finalized (transition to `MATCHED`) and published with the matches from the
  catalogs that succeeded — provided at least one catalog succeeded.
- **R3.** If zero catalogs succeed for a batch (broad outage), the batch fails
  closed — revert/retry as today — and publishes nothing.
- **R4.** Each affected alert's crossmatch records which catalog(s) were skipped,
  so downstream consumers can tell which catalogs a published crossmatch covers.
- **R5.** Catalog-skip events are observable to operators.
- **R6.** The retry-handler `'ServerDisconnectedError' object is not subscriptable`
  `TypeError` is fixed so the transient-error path handles fsspec-wrapped errors
  cleanly.

### Scope Boundaries

**In scope**
- Per-catalog skip after read-retry exhaustion, continuing the batch.
- The ≥1-success guard (zero success → revert/retry).
- Marking each affected alert's crossmatch with the skipped catalog(s).
- Observability for catalog-skip events.
- Fixing the retry-handler `TypeError`.

**Out of scope**
- Backfilling / re-crossmatching a skipped catalog when it recovers — an alert
  crossmatched during an outage stays partial (no backfill).
- Required-vs-optional per-catalog configuration.
- The transient-retry mechanism itself — retry still happens first; skip only
  after it gives up.
- The mid-batch worker-kill recovery (separate plan
  `docs/plans/2026-07-20-001-fix-crossmatch-batch-kill-recovery-plan.md`).
- The DES/DELVE S3 switch (done, `docs/plans/2026-07-20-002-...`) and SkyMapper's
  own hosting (it has no S3 mirror).

### Success Criteria

- **AE1.** A batch where one catalog persistently fails still finalizes and
  publishes the affected alerts with the other catalogs' matches, marked partial;
  the batch does not revert.
- **AE2.** Shipping this drains the PROD backlog: with SkyMapper skipped, the
  Gaia/DES/DELVE matches persist, alerts reach `NOTIFIED`, publications resume,
  and the 337k `INGESTED` backlog clears.
- **AE3.** A batch where all catalogs fail reverts (fail-closed) and publishes
  nothing.
- **AE4.** A published crossmatch's payload lets a consumer tell which catalogs
  were covered vs skipped.
- **AE5.** Operators can see when a catalog is being skipped (metric / log).

### Key Decisions

- **KD1.** Best-effort skip-and-mark, no backfill. _(session-settled 2026-07-20.)_
- **KD2.** ≥1-success guard — zero success reverts (fail-closed).
  _(session-settled 2026-07-20.)_
- **KD3.** "Persistent failure" = read retries exhausted; transient-retry
  unchanged. _(session-settled 2026-07-20.)_

---

## Key Technical Decisions

- **KTD1 — best-effort skip-and-mark, no backfill.** _(session-settled:
  user-directed — chosen over publish-now-backfill-later and required-vs-optional
  catalogs: timeliness over eventual completeness for a transient alert stream.)_
- **KTD2 — ≥1-success guard; zero success fails closed.** _(session-settled:
  user-directed — chosen over pure best-effort and a configurable floor: a total
  outage must not publish empty crossmatches indistinguishable from real "no
  matches".)_
- **KTD3 — "persistent" = read retries exhausted; skip only after the existing
  retry wrapper gives up.** _(session-settled: user-directed — chosen over
  skip-on-first-error: transient blips should still retry.)_
- **KTD4 — skip replaces the fatal `raise`.** In the catalog loop
  (`tasks/crossmatch.py:81-89`), a read error surfacing from `crossmatch_alerts`
  is handled like the existing no-overlap case (line 75-79): log, record the
  catalog in a `skipped` set, and `continue` — rather than re-raising into the
  batch-abort. Track `succeeded` (read completed) and `skipped` (read errored)
  catalog sets across the loop.
- **KTD5 — success = a completed read; a skip is not a success (resolves OQ4).**
  A catalog counts toward the ≥1-success guard when its read completes — matches,
  empty, or no-overlap all count; only a read error counts as a skip. After the
  loop, if `succeeded` is empty (every catalog errored), raise so the existing
  outer handler reverts the batch to `INGESTED`; if ≥1 succeeded, run the existing
  atomic `MATCHED` + notifications transition.
- **KTD6 — coverage mark lives in the published payload, not a model field
  (resolves OQ1, OQ3).** `build_published_payload` (`matching/payload.py`) gains a
  top-level `catalogs_skipped` list (and a `partial` boolean) populated from the
  batch's `skipped` set — a consumer-facing contract addition, so **no DB
  migration**. It is recorded per published notification (which is per match) and
  reflects the per-batch skip set. Alerts with zero matches produce no
  notification (unchanged), so their partial-ness is not published — accepted.
- **KTD7 — observability = a counter plus a warning (resolves OQ2).** Add a
  Prometheus counter (e.g. `catalog_skips_total{catalog=...}`) in
  `crossmatch/core/metrics.py`, incremented on skip, plus a structured `warning`
  log on skip. Alert-thresholding is left to the monitoring layer, out of scope
  here.
- **KTD8 — surface the fsspec-wrapped connection error clearly (resolves R6).**
  The underlying `ServerDisconnectedError` reaches the retry wrapper wrapped as a
  `TypeError` ("not subscriptable"). `_is_transient_read_error` already detects it
  by message text (so retries fire), but the handling/log should surface the
  underlying transient connection error rather than the confusing `TypeError`.

---

## Implementation Units

> All paths are in the app repo `crossmatch-service`. No DB migration (the
> coverage mark is a JSON-payload field). No new dependencies.

### U1. Skip a persistently-failing catalog instead of aborting the batch

- **Goal:** A catalog read error (after retries) skips that catalog and continues
  the batch, tracking which catalogs succeeded vs were skipped, and surfacing the
  skip to operators — instead of re-raising into the whole-batch revert.
- **Requirements:** R1, R5; implements KTD1, KTD4, KTD7.
- **Dependencies:** none.
- **Files:** `crossmatch/tasks/crossmatch.py`, `crossmatch/core/metrics.py`,
  `crossmatch/tests/test_crossmatch_catalog_skip.py` (new).
- **Approach:** In the `except Exception:` arm at lines 81-89, replace `raise`
  with: a `warning` log ("catalog skipped after read failure"), add the catalog to
  a `skipped` set, increment the new skip counter, and `continue`. Maintain a
  `succeeded` set for catalogs whose read completed (the no-overlap `continue`,
  the empty-result `continue`, and the matches-written path all mark success).
  Add `CATALOG_SKIPS = Counter('catalog_skips_total', ..., ['catalog'])` in
  `core/metrics.py` beside `CROSSMATCH_MATCHES`/`CROSSMATCH_BATCHES`.
- **Execution note:** Proof-first — write the failing test (one catalog raises,
  batch should continue) before changing the loop, to pin the exact revert→skip
  behavior change.
- **Patterns to follow:** the existing no-overlap graceful skip (`tasks/crossmatch.py:75-79`);
  the existing metrics in `core/metrics.py`.
- **Test scenarios:**
  - Covers AE1. One catalog's `crossmatch_alerts` raises (mock it to raise after
    retries); the loop continues, the other catalogs' matches are written, and the
    batch reaches the `MATCHED` transition — no revert.
  - No-spatial-overlap on a catalog still skips gracefully (unchanged behavior).
  - A single unbuildable match row still skips just that row (unchanged), not the
    catalog.
  - The skip increments `catalog_skips_total{catalog=<name>}` and emits a
    `warning` log naming the catalog.
- **Verification:** a batch with one raising catalog completes with the other
  catalogs' matches persisted; the skip counter and warning fire.

### U2. Require at least one successful catalog before finalizing

- **Goal:** The batch finalizes only when ≥1 catalog succeeded; if every catalog
  errored, it fails closed (reverts to `INGESTED`) and publishes nothing.
- **Requirements:** R3 (AE3); implements KTD2, KTD5.
- **Dependencies:** U1 (needs the `succeeded`/`skipped` tracking).
- **Files:** `crossmatch/tasks/crossmatch.py`,
  `crossmatch/tests/test_crossmatch_catalog_skip.py`.
- **Approach:** After the catalog loop and before the atomic `MATCHED` +
  notifications transition (line 160), if `succeeded` is empty, raise (a dedicated
  exception type or a re-raise of the last error) so the existing outer
  `except Exception:` reverts the batch and re-raises. A skipped catalog does not
  count as a success (KTD5).
- **Execution note:** Proof-first — write the all-catalogs-fail test first.
- **Test scenarios:**
  - Covers AE3. Every catalog raises → the batch reverts to `INGESTED`
    (`queued_at=None`), no `Notification` rows are created, and alerts do not reach
    `MATCHED`.
  - Exactly one catalog succeeds (others skipped) → the batch finalizes and
    publishes (guard passes at the boundary).
  - A batch where all catalogs read successfully but return zero matches still
    finalizes (no-match is success, not failure).
- **Verification:** all-fail batch reverts and publishes nothing; ≥1-success batch
  finalizes.

### U3. Mark skipped-catalog coverage in the published payload

- **Goal:** Each published notification records which catalogs were skipped in its
  batch, so a consumer can tell the crossmatch's coverage.
- **Requirements:** R4 (AE4); implements KTD6.
- **Dependencies:** U1 (needs the `skipped` set).
- **Files:** `crossmatch/matching/payload.py`, `crossmatch/tasks/crossmatch.py`,
  `crossmatch/tests/test_payload.py` (extend) or a new payload test.
- **Approach:** Add a top-level `catalogs_skipped` list and a `partial` boolean to
  `build_published_payload`; thread the batch's `skipped` set into each
  `build_published_payload` call in the match-building loop. `partial` is true iff
  `catalogs_skipped` is non-empty. Keep existing payload keys unchanged (additive).
- **Test scenarios:**
  - Covers AE4. A batch with SkyMapper skipped → every published payload has
    `catalogs_skipped=["skymapper_dr4"]` and `partial=true`.
  - A batch with no skips → `catalogs_skipped=[]` and `partial=false`.
  - The new keys are JSON-native and do not disturb existing top-level metadata or
    the nested `catalog_payload`.
- **Verification:** published payloads carry accurate `catalogs_skipped`/`partial`;
  existing payload tests still pass.

### U4. Handle the fsspec-wrapped connection error cleanly

- **Goal:** The `ServerDisconnectedError`-wrapped-as-`TypeError` case is detected
  and logged as the transient connection error it is, not a confusing
  "not subscriptable" `TypeError`.
- **Requirements:** R6.
- **Dependencies:** none (independent of U1-U3).
- **Files:** `crossmatch/matching/catalog.py`,
  `crossmatch/tests/test_catalog_read_retry.py` (extend).
- **Approach:** In `_read_with_retry` / `_is_transient_read_error`, ensure a
  `TypeError` whose message/chain names a known transient connection error (e.g.
  `ServerDisconnectedError`, `ConnectionTimeoutError`) is classified transient and
  logged with the underlying cause, rather than surfacing the raw
  "object is not subscriptable" text. Keep the existing message-text detection;
  add the clearer logging/normalization.
- **Test scenarios:**
  - A `TypeError("'ServerDisconnectedError' object is not subscriptable")` is
    detected as transient (retried), matching the existing message-text tests.
  - The logged/normalized error names the underlying connection failure, not the
    subscriptable `TypeError`.
  - Deterministic errors (bad columns, version skew) are still not transient
    (unchanged).
- **Verification:** `test_catalog_read_retry.py` passes including the new case; the
  transient path logs the real cause.

---

## Verification Contract

- **Skip, don't abort (U1):** a batch with one persistently-failing catalog
  continues, persists the other catalogs' matches, and finalizes — no revert;
  `catalog_skips_total` increments. (R1, R5, AE1)
- **≥1-success guard (U2):** an all-catalogs-fail batch reverts to `INGESTED`,
  creates no notifications, and does not advance `MATCHED`; a ≥1-success batch
  finalizes. (R2, R3, AE3)
- **Coverage mark (U3):** published payloads carry accurate
  `catalogs_skipped`/`partial`; existing payload keys unchanged. (R4, AE4)
- **Retry handling (U4):** the fsspec-wrapped `ServerDisconnectedError` is treated
  as transient and logged clearly. (R6)
- **Suite green:** `python -m pytest` passes in-container (per `docs/developer.md`),
  including `test_crossmatch_notify_ordering.py`, `test_dispatch_notifications.py`,
  and `test_catalog_read_retry.py`.

## Definition of Done

- A single persistently-failing catalog is skipped (logged + counted); the batch
  finalizes with the other catalogs' matches, marked partial.
- Zero-success batches fail closed (revert, publish nothing).
- Published payloads carry `catalogs_skipped`/`partial`.
- The fsspec-wrapped connection error is handled cleanly.
- Existing test suite green; new tests cover AE1/AE3/AE4 and the retry case.
- (Deploy-time, out of this change's DoD but the payoff: once shipped and
  promoted, PROD's 337k backlog drains — SkyMapper skipped, Gaia/DES/DELVE matches
  persist and publish.)

## Assumptions (pipeline-resolved open questions)

- **OQ1/OQ3 → KTD6:** coverage recorded as `catalogs_skipped`/`partial` in the
  published payload (no model field, no migration); per-notification, reflecting
  the per-batch skip set; zero-match alerts publish nothing so their partial-ness
  is not surfaced (accepted).
- **OQ2 → KTD7:** observability = `catalog_skips_total{catalog}` counter + a
  `warning` log; alert-thresholding left to the monitoring layer.
- **OQ4 → KTD5:** a skipped catalog does not count toward the ≥1-success guard.
