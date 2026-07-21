---
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-brainstorm
type: fix
execution: code
date: 2026-07-20
---

# Crossmatch Batch Kill Recovery - Plan

## Goal Capsule

- **Objective:** When a celery-worker is killed mid-batch (deployment rollout,
  OOM, node loss, any SIGKILL), the crossmatch pipeline resumes automatically
  within ~10-15 minutes instead of stalling for up to an hour, with no manual
  database intervention.
- **Product authority:** Maintainer/developer (Scott Koranda).
- **Open blockers:** None. U3's runtime measurement is **done** (real PROD 100k
  batches: 3.0-4.3 min): the values are set — `soft=480s`, `hard=600s`, `stuck=780s`
  — and R1's ~10-15 min target is confirmed achievable (recovery ≈ 13 min). See KTD6.

## Product Contract

### Problem

`dispatch_crossmatch_batch` (`crossmatch/tasks/schedule.py`) marks up to
`CROSSMATCH_BATCH_MAX_SIZE` (100,000) alerts as `QUEUED` and enqueues
`crossmatch_batch` (`crossmatch/tasks/crossmatch.py`). `crossmatch_batch` reverts
its alerts to `INGESTED` **only if it raises**. A hard kill gives it no chance to
revert, so the batch is stranded in `QUEUED`. The scheduler's concurrency guard
then refuses to dispatch any new batch while `QUEUED` alerts exist, until they
age past `CROSSMATCH_BATCH_STUCK_SECONDS` (3600s), when auto-recovery finally
reverts them.

During that up-to-1-hour window the entire pipeline halts — no crossmatches, no
matches, no notifications, no Hopskotch publications — while `INGESTED` alerts
pile up behind the block. Observed on PROD 2026-07-20 after a routine `0.6.1`
rollout: 100,000 alerts stuck `QUEUED` + 224,000 `INGESTED` backlog, ~1h stall.
The auto-recovery is correct but far too slow, because the stuck threshold (1h)
is ~10x the real batch runtime (single-digit minutes).

### Requirements

- **R1.** After a worker is killed mid-batch by any mechanism (rollout, OOM, node
  loss, SIGKILL), crossmatch dispatch resumes automatically within ~10-15 minutes,
  with no manual database action.
- **R2.** Recovery must not depend on the worker receiving or handling a catchable
  shutdown signal — it must cover uncatchable kills, not just graceful drains.
- **R3.** The recovery timer must never reclaim a batch that is still legitimately
  running. Bound a batch's maximum *execution* runtime *below* the recovery
  threshold via a **soft** Celery time limit on `crossmatch_batch`, so an
  overrunning batch reverts its own alerts through the existing on-raise path
  rather than being falsely reclaimed while alive. The threshold is compared
  against `queued_at` (stamped at *dispatch*) while the time limit bounds
  execution from *worker pickup*, so the threshold must exceed **task time limit +
  worst-case broker/pickup latency + clock-skew allowance**, not merely the time
  limit — otherwise a batch that sat queued during a rollout can be reclaimed
  while still alive (creating the concurrent re-run R5 forbids). Alternatively,
  re-anchor the stuck-age on a `started_at` stamped when `crossmatch_batch` begins
  executing, so the timer and the limit share one clock origin.
- **R4.** A batch that hits its **soft** time limit — including a hung or stalled
  Dask job — self-heals by reverting its alerts to `INGESTED` for re-dispatch,
  instead of blocking the pipeline indefinitely. Only the soft limit raises a
  catchable `SoftTimeLimitExceeded` that the on-raise path handles; a hard-only
  limit SIGKILLs the worker child without reverting, so a hard limit is a backstop,
  not the self-heal mechanism. A hung Dask/LSDB call may not honor the soft limit
  until it returns to Python, so for a truly stalled job the stuck-timer reclaim —
  not the revert — is the worst-case guarantee.
- **R5.** Recovery introduces no new duplicate publications beyond the system's
  existing at-least-once semantics. A batch killed before finalization has
  published nothing, and downstream consumers already dedupe on `diaObjectId`.
- **R6.** Recovery requires no operator action — no manual SQL, no restart.

### Scope Boundaries

**In scope**
- A **per-task** soft time limit on `crossmatch_batch` (e.g.
  `@shared_task(soft_time_limit=...)`) bounding its runtime — NOT the global
  `CELERY_TASK_SOFT_TIME_LIMIT` / `CELERY_TASK_TIME_LIMIT`, which also govern the
  antares/lasair/pittgoogle ingest consumers and flower and so cannot be lowered
  without starving ingestion. A hard time limit may backstop the soft one.
- Lowering `CROSSMATCH_BATCH_STUCK_SECONDS` from 3600s to above the per-task limit
  plus the worst-case queue/pickup + clock-skew margin (see R3).
- Measuring real batch runtime to set both values.
- App repo only: `crossmatch/tasks/crossmatch.py`, `crossmatch/tasks/schedule.py`,
  `crossmatch/project/settings.py`.

**Out of scope**
- Heartbeat / lease near-real-time (<1 min) recovery — over-engineered for the
  chosen ~10-15 min target.
- A SIGTERM graceful-drain that lets *planned* rollouts recover with zero wait —
  the timer already covers rollouts; noted as a future nicety, not built now.
- Preventing worker kills or changing the deployment/rollout strategy.
- Concurrent multi-batch processing — single-batch-at-a-time semantics are retained.
- Any change to how matches or notifications are computed or published.
- Reducing `CROSSMATCH_BATCH_MAX_SIZE` to shrink batch runtime or blast radius —
  the size is owned by the LSDB-developer consultation, not this fix (see KD5).

### Success Criteria

- **AE1.** Simulate a hard kill mid-batch (e.g. delete the worker pod during a
  running batch): the `QUEUED` alerts revert to `INGESTED` and a new batch
  dispatches within ~10-15 minutes, unattended.
- **AE2.** A batch that runs past its **soft** time limit reverts its alerts via
  the on-raise path and does not remain `QUEUED` past the threshold.
- **AE3.** Under normal operation, a batch that completes within the time limit is
  never reverted by the recovery timer (no false reclaim of a live batch).
- **AE4.** None of the above requires a manual database action to recover.
- **AE5.** A batch held in the broker queue past the recovery threshold *before* a
  worker picks it up is not reclaimed and re-dispatched while it later runs to
  completion — i.e. no concurrent duplicate run arises from queue/pickup latency.

### Key Decisions

- **KD1.** Timer-based recovery over heartbeat/lease — signal-independent and
  simple; the relaxed ~10-15 min target makes near-real-time reclaim unnecessary.
  _(session-settled 2026-07-20: all-abrupt-kills scope + relaxed recovery target.)_
- **KD2.** Bound batch runtime with a task time limit so the lowered stuck-timer is
  provably safe against reclaiming a live batch — chosen because worst-case runtime
  is not yet known. _(session-settled 2026-07-20.)_
- **KD3.** Retain single-batch-at-a-time concurrency (shared Dask cluster); the
  concurrency guard stays — only its threshold changes.
- **KD4.** Accept at-least-once semantics; no new dedup work — consumers already
  dedupe on `diaObjectId`. _(session-settled earlier 2026-07-20, from the notifier
  delivery-confirmation work.)_
- **KD5.** `CROSSMATCH_BATCH_MAX_SIZE` stays at ~100k, set in direct consultation
  with the LSDB developers; it may drift a little as library experience grows but
  is deliberately **not** tuned as a lever for kill-recovery — the recovery bound
  comes from the per-task time limit and stuck threshold (R3/KD2), not from
  shrinking batches. _(session-settled 2026-07-21: user-directed — settles the
  batch-size-as-recovery-lever question, distinct from the current OQ3 on
  `CatalogMatch` idempotency.)_

### Outstanding Questions

- **OQ1.** Actual typical and worst-case batch runtime — drives the exact task
  time-limit and `CROSSMATCH_BATCH_STUCK_SECONDS` values. Measure before finalizing
  numbers.
- **OQ2.** Whether to add a hard Celery time limit as a backstop to the soft one,
  and how to size it. The on-raise revert already catches `SoftTimeLimitExceeded`
  (it subclasses `Exception`, caught by `crossmatch_batch`'s outer `except
  Exception`), so the clean revert fires under a soft limit — this sub-question is
  resolved; only the hard-backstop choice is open. Narrow caveat to verify: the
  per-row `except Exception: continue` in the match-build loop could swallow a
  single `SoftTimeLimitExceeded` if it lands mid-row-build; confirm the soft limit
  still ultimately reverts.
- **OQ3.** Whether a killed batch can leave partial `CatalogMatch` rows that a
  re-run would duplicate, and if so whether revert/re-run needs cleanup to stay
  idempotent. (Likely benign: `CatalogMatch` has the `unique_catalog_match`
  constraint and `bulk_create(ignore_conflicts=True)`, so a re-run at the same
  `match_version` re-inserts idempotently; confirm the `Notification` path, which
  does not set `ignore_conflicts`.)

_Planning resolution: OQ1 → U3 (measurement). OQ2 → resolved (KTD2 soft-catch
verified; KTD3 hard backstop; KTD4 per-row hardening). OQ3 → KTD7 + U1 tests._

---

## Planning Contract

_Product Contract preservation: **unchanged** by this enrichment — R1-R6, AE1-AE5,
KD1-KD5 are carried verbatim with stable IDs. The sections below add the HOW only._

_Of the three in-scope files, `crossmatch/tasks/schedule.py` is **read-only** for
this fix — its recovery behavior changes only through the `settings.py` value it
reads (U2); no unit modifies it (KD3)._

---

## Key Technical Decisions

- **KTD1 — Per-task soft (+ hard) time limit on `crossmatch_batch`, not the global
  setting.** Set `soft_time_limit` and `time_limit` on the `@shared_task` decorator
  at `crossmatch/tasks/crossmatch.py:14`, leaving the global
  `CELERY_TASK_SOFT_TIME_LIMIT` / `CELERY_TASK_TIME_LIMIT` untouched. _(session-settled:
  user-directed — chosen over lowering the global setting: the global also bounds
  the antares/lasair/pittgoogle ingest consumers and flower and would starve
  ingestion. Instantiates KD2.)_
- **KTD2 — The soft limit is the self-heal; the on-raise revert already catches
  it.** `SoftTimeLimitExceeded` subclasses `Exception`, so it is caught by
  `crossmatch_batch`'s outer `except Exception` (`crossmatch/tasks/crossmatch.py:224`)
  which reverts alerts to `INGESTED` and re-raises. Verified in code — no outer-handler
  change needed. _(Resolves OQ2's exception-coverage sub-question; instantiates R4/KD2.)_
- **KTD3 — Add a hard `time_limit` as a SIGKILL backstop above the soft limit.** A
  truly hung Dask/LSDB call may never return to Python for the soft signal to fire;
  the hard limit kills the worker child (no self-revert on SIGKILL), and the
  stuck-timer reclaim (U2) then recovers its alerts. _(Resolves OQ2's hard-backstop
  choice; supports R4's worst-case.)_
- **KTD4 — Harden the per-row handler so it cannot swallow `SoftTimeLimitExceeded`.**
  The per-row `except Exception: continue` (`crossmatch/tasks/crossmatch.py:167`)
  would eat a soft-limit exception raised mid-row-build, defeating the self-revert.
  Re-raise `SoftTimeLimitExceeded` from that handler before the generic swallow.
  _(Resolves OQ2's per-row caveat; supports R4.)_
- **KTD5 — Fix the false-reclaim race with a margin, not a re-anchor.** Set
  `CROSSMATCH_BATCH_STUCK_SECONDS` above `soft_limit + worst-case broker/pickup
  latency + clock-skew allowance`, rather than adding a `started_at` field to
  re-anchor the stuck-age. _(session-settled: user-directed — chosen over the
  `started_at` re-anchor: config-only, no migration, and the relaxed ~10-15 min
  target plus single-batch semantics make the margin sufficient. The re-anchor is
  kept under Alternatives. Instantiates R3/KD1; resolves AE5.)_
- **KTD6 — Recovery time is bounded below by worst-case batch runtime — measured,
  R1 achievable.** The soft limit must exceed the worst-case *legit* 100k-batch
  runtime (else legit batches self-revert before completing — a livelock) and the
  stuck threshold must exceed the soft limit, so **recovery ≈ worst-case runtime +
  margin**. U3 measured it against real PROD batches: 100k runs in **3.0-4.3 min**
  (strongly sub-linear, catalog-read-bound), so `soft_limit=480s` (8 min) clears the
  worst case with ~1.9× headroom and `stuck_threshold=780s` gives ~13 min recovery —
  **inside R1's ~10-15 min**. The contingency this KTD flagged is resolved favorably
  (batch size stayed fixed per KD5, no heartbeat per KD1); re-measure only if
  catalog-read latency regresses materially.
- **KTD7 — Idempotency relies on the existing unique constraint; no new dedup
  code.** A killed batch publishes nothing (Notifications are created atomically
  with the `MATCHED` transition, step 4, which the killed batch never reaches), and
  re-run `CatalogMatch` writes are idempotent via `unique_catalog_match` +
  `bulk_create(ignore_conflicts=True)` at the same `match_version`. U1 verifies;
  add `ignore_conflicts` to the `Notification` bulk_create only if a re-run path is
  found that reaches it. _(Resolves OQ3; instantiates R5/KD4.)_

---

## High-Level Technical Design

The fix is a set of ordering constraints on the `queued_at` timeline, not new
control flow. A `QUEUED` batch is in one of two states, and the timer must reclaim
the dead one while never touching the live one:

```
  dispatch            worker pickup                          soft      hard
  (queued_at)         (task start)                           limit     limit
      |------ pickup ------|============ execution ===========|--grace--|
      |                                                       |         |
      |------------------ stuck_threshold --------------------------|--> reclaim
                        (measured from queued_at)

  Ordering constraint (so the timer never reclaims a LIVE batch):
      worst_case_runtime  <  soft_limit  <  hard_limit
      soft_limit + pickup_latency + clock_skew  <  stuck_threshold  (<= recovery target)
```

- **Live overrun** (batch running past `soft_limit`): the soft limit raises
  `SoftTimeLimitExceeded` → on-raise revert → re-dispatch. Self-heals *before* the
  timer can reclaim it (that is what the ordering constraint guarantees). AE2/AE3.
- **Hard kill** (task died after pickup, or never picked up during a rollout):
  `queued_at` ages with no self-revert; at `stuck_threshold` the dispatcher's
  existing auto-recovery reverts `QUEUED → INGESTED` and re-dispatches. Recovery ≈
  `stuck_threshold`. AE1.
- **Pickup-window race** (AE5): a task can sit in the broker between `queued_at`
  and pickup; the `+ pickup_latency + clock_skew` term in the constraint keeps the
  threshold from reclaiming it before a worker starts it.

Measured values (U3, from real PROD 100k batches — worst observed 258s / 4.3 min):
`soft_limit = 480s` (8 min, ~1.9× worst-case), `hard_limit = 600s` (10 min),
`stuck_threshold = 780s` (13 min; ≈ 5 min margin over soft for pickup + skew;
recovery ≈ 13 min, inside R1's ~10-15 min).

---

## Implementation Units

### U1. Per-task soft + hard time limit on `crossmatch_batch`, soft-exception-safe

- **Goal:** Bound `crossmatch_batch` runtime so an overrunning *live* batch
  self-reverts (soft limit) and a truly hung one is killed (hard limit), without
  the per-row handler swallowing the soft exception.
- **Requirements:** R2, R3, R4; implements KTD1, KTD2, KTD3, KTD4, KTD7.
- **Dependencies:** U3 (runtime measurement — completed this session; the values
  below are the measured, final ones, not provisional).
- **Files:** `crossmatch/tasks/crossmatch.py` (the `@shared_task` decorator at
  line 14; the per-row `except` at line ~167), `crossmatch/tests/test_crossmatch_time_limit.py`
  (new).
- **Approach:** add `soft_time_limit=480` and `time_limit=600` (the U3-measured
  values) to `@shared_task(name="crossmatch_batch", ...)`. Import
  `celery.exceptions.SoftTimeLimitExceeded` and re-raise it at the top of the
  per-row `except` before the generic `continue`. Confirm (do not change) that the
  per-catalog handler (line 83, `is_transient_read_error(exc)` is False → `raise`)
  and the outer `except Exception` (line 224, revert + re-raise) already carry the
  soft exception through to the revert.
- **Execution note:** proof-first — write the failing revert tests (soft exception
  raised from `crossmatch_alerts`, and raised mid-row-build) before adding the
  decorator and the per-row guard.
- **Patterns to follow:** the revert path (`crossmatch/tasks/crossmatch.py:224`)
  and the test style in `crossmatch/tests/test_crossmatch_fail_loud.py` (monkeypatch
  `crossmatch_alerts`, `AlertFactory(status=QUEUED)`, assert alert status).
- **Test scenarios:**
  - Covers AE2. `crossmatch_alerts` raises `SoftTimeLimitExceeded` during compute →
    all alerts revert to `INGESTED`, no `Notification` rows, task re-raises.
  - `SoftTimeLimitExceeded` raised during the per-row build loop → NOT swallowed by
    the per-row `except` → batch still reverts (guards KTD4).
  - A normal batch completing under the limit reaches `MATCHED` with no false revert.
  - Idempotency (KTD7 / OQ3): a batch that wrote some `CatalogMatch` rows then
    reverted, re-run at the same `match_version`, creates no duplicate `CatalogMatch`
    rows (`unique_catalog_match` + `ignore_conflicts`); and produces no duplicate
    `Notification` rows (the reverted batch never reached finalization).
- **Verification:** the new tests pass in-container; a soft-limit exception at any
  point leaves alerts `INGESTED`, never stranded `QUEUED`.

### U2. Lower `CROSSMATCH_BATCH_STUCK_SECONDS` with the pickup/skew margin

- **Goal:** Shrink the recovery threshold from 3600s to `soft_limit + margin` so a
  hard-killed batch is reclaimed within the target, without falsely reclaiming a
  queued-but-live batch.
- **Requirements:** R1, R2, R3, R6; implements KTD5, KTD6.
- **Dependencies:** U3 (measurement — done; value below is final), U1 (the soft
  limit must exist and sit below the new threshold).
- **Files:** `crossmatch/project/settings.py` (the `CROSSMATCH_BATCH_STUCK_SECONDS`
  default + a comment stating the ordering constraint from the HTD),
  `crossmatch/tests/test_dispatch_crossmatch_batch.py` (extend the stuck-recovery
  path).
- **Approach:** lower the default to the U3-measured `780s` (13 min). Add
  the ordering-constraint comment at the setting. **No logic change to
  `schedule.py`** — the dispatcher's concurrency guard already auto-recovers
  `QUEUED` alerts older than the threshold (the `age >= stuck_threshold` branch in
  `dispatch_crossmatch_batch`); only the value changes (KD3 — the guard stays, only
  its threshold moves).
- **Test scenarios:**
  - Covers AE1's reclaim mechanism. A `QUEUED` batch whose `queued_at` age exceeds
    the new threshold is auto-recovered to `INGESTED` and re-dispatched.
  - Covers AE3/AE5. A `QUEUED` batch younger than the threshold is not reclaimed
    (no false reclaim inside the pickup+skew margin).
- **Verification:** at the new value, a simulated stuck batch is reclaimed within
  the target window and a fresh `QUEUED` batch is untouched.

### U3. Measure runtime to set the values, then the DEV hard-kill drill (both done)

_Runs first — U1/U2 depend on its values. Both the measurement and the DEV
hard-kill drill are **complete** (2026-07-21); results below._

**Measured runtimes (PROD, 2026-07-21):**

| Batch size | Observed runtime | Sample | Version |
|---|---|---|---|
| 100,000 | 177-258s (3.0-4.3 min) | 4 batches | v0.6.1 (HTTPS DES/DELVE) |
| 37,036 | ~90s (1.5 min) | 1 batch | v0.6.1 |
| ~3.9k-4.4k | 49-92s | 4 batches | v0.7.0 (S3 DES/DELVE) |

Runtime is strongly **sub-linear** (catalog-read-bound, not alert-count-bound):
100k is only ~3x the 4k time at 25x the alerts. 258s is a conservative worst case
— it is v0.6.1 (HTTPS DES/DELVE); v0.7.0 (S3 + flaky-catalog skip) only improves it.

- **Goal:** Measure real `crossmatch_batch` runtime to set the three values, then
  validate the recovery target end-to-end on DEV.
- **Requirements:** R1, R3; implements KTD6; resolves OQ1.
- **Dependencies:** none for the measurement (runs first, done); the DEV hard-kill
  drill depends on U1 and U2 being in place.
- **Files:** none for the measurement; optionally a `docs/solutions/` note recording
  the measured runtimes. U1/U2 carry the resulting values.
- **Approach (measurement — completed 2026-07-21):** reconstructed real batch
  runtime from PROD by grouping alerts on `queued_at` (one batch per dispatch) and
  taking last `CatalogMatch.created_at` − `queued_at` (see the runtimes table above).
  Chosen values: `soft_limit=480s` (~1.9× the 4.3 min worst case), `hard_limit=600s`,
  `stuck_threshold=780s` → recovery ≈ 13 min, inside R1. The KTD6 contingency is
  **resolved favorably** — R1's target is achievable at the fixed 100k batch size (KD5).
- **Execution note:** measurement and the DEV hard-kill drill are both done; the
  values are final and the recovery behavior is validated end-to-end (results below).
- **Test scenarios:** Test expectation: none — measurement + operational validation;
  automated behavioral coverage lives in U1/U2. The hard-kill drill is an operational
  verification, not a unit test.
- **Verification — DEV hard-kill drill PASSED (2026-07-21, on v0.8.0):** seeded a
  running batch (8,000 alerts), then SIGKILLed the worker (`--grace-period=0
  --force`) 28s into the batch — an uncatchable kill, so the on-raise revert never
  ran (R2). The 8,000 alerts stranded `QUEUED`; the dispatcher's stuck-timer
  auto-recovered them at **exactly `queued_at + 780s` (13.0 min)** — logged
  `Auto-recovered stuck QUEUED alerts count=8000 oldest_age_seconds=780.15` — then
  reverted to `INGESTED`, re-dispatched, and re-crossmatched all 8,000 back to
  `MATCHED`/`NOTIFIED`. Covers AE1 (recovery inside the ~10-15 min target), AE4 (no
  manual DB action), R2 (signal-independent), and R5 (idempotent re-run + the
  operator-visible warning log). Before this change the same kill would have stalled
  the pipeline for up to 1 hour (the old 3600s threshold).

---

## Verification Contract

- U1 and U2 unit tests pass in-container (`pytest` via the compose worker, per
  `docs/developer.md`).
- AE2/AE3/AE5, and AE1's reclaim mechanism, are covered by U1/U2 automated tests;
  AE1 and AE4 were verified end-to-end by the U3 DEV hard-kill drill (**passed
  2026-07-21 on v0.8.0** — recovery at exactly `queued_at + 780s` / 13.0 min; see U3).
- The `soft_limit` (480s) sits above the U3-measured worst-case 100k runtime (258s)
  with ~1.9× headroom (KTD6); confirm no false reverts of legit batches during the
  post-deploy DEV/PROD soak.
- Changed Python files are `black`-formatted (scoped to the diff); the full suite
  is green in-container before the work is called done.
- Idempotency (KTD7) holds: a revert/re-run produces no duplicate `CatalogMatch` or
  `Notification` rows.

---

## Risks & Dependencies

- **Risk (KTD6) — R1 target was runtime-contingent; now measured and met.** U3
  measured real 100k batches at 3.0-4.3 min, so `soft_limit=480s` clears the worst
  case and recovery ≈ 13 min (inside R1) at the fixed 100k size. Residual: if
  catalog-read latency regresses materially (a degraded source, a new heavier
  catalog), 100k runtime could climb toward the soft limit — re-measure and re-tune;
  the numbers, not the mechanism, would change.
- **Risk (KTD5) — the margin is probabilistic, not a hard guarantee.** A pathological
  rollout that holds the task in the broker beyond the ~5 min margin could still
  false-reclaim a live batch. Mitigation: the ~5 min margin comfortably exceeds the
  observed rollout pickup (~1-2 min); the `started_at` re-anchor (Alternatives) is
  the hard-guarantee fallback if the margin proves insufficient in practice.
- **Risk (R4) — a hung Dask call may not honor the soft limit** until it returns to
  Python. The hard limit + stuck-timer reclaim are the backstop; recovery for a
  truly hung call is the stuck-timer path (no self-revert), within `stuck_threshold`.
- **Dependency — prefork pool.** Soft time limits are delivered via `SIGUSR1`, which
  only works on the prefork worker pool; the worker runs the default prefork pool
  (`run_celery_worker.sh`, no `--pool` override), so this holds. A future switch to a
  threads/gevent pool would silently disable soft limits.

---

## Alternatives Considered

- **`started_at` re-anchor (rejected as primary — KTD5).** Stamp a `started_at`
  when `crossmatch_batch` begins executing and measure the stuck-age from it, so the
  timer and the time limit share one clock origin. More robust for the pickup-window
  race, but needs a new `Alert` field + migration (outside the config-only scope)
  and does not help the long-legit-batch constraint (the soft limit does). Kept as
  the fallback if the margin (KTD5) proves insufficient.
- **Lowering the global Celery time limit (rejected — KTD1).** Simplest edit, but
  `CELERY_TASK_*_TIME_LIMIT` also governs the ingest consumers and flower, so it
  would starve ingestion.
- **Heartbeat / lease recovery (rejected upstream — KD1).** Near-real-time reclaim
  but signal- and complexity-heavy; the relaxed ~10-15 min target does not need it.

---

## Definition of Done

- Runtime measured (U3, done): real 100k batches 3.0-4.3 min → values set
  `soft=480s`, `hard=600s`, `stuck=780s`; recovery ≈ 13 min (inside R1).
- `soft_time_limit=480` + hard `time_limit=600` on `crossmatch_batch`, and the
  per-row `except` re-raises `SoftTimeLimitExceeded` (U1).
- `CROSSMATCH_BATCH_STUCK_SECONDS` lowered to 780s with the documented
  ordering-constraint comment; the dispatcher guard reclaims stuck batches at the new
  value (U2).
- The DEV hard-kill drill **passed** (U3, 2026-07-21 on v0.8.0): a SIGKILL mid-batch
  stranded 8,000 alerts `QUEUED`; the stuck-timer reclaimed them to `INGESTED` and
  re-dispatched at exactly `queued_at + 780s` (13.0 min), unattended, and all 8,000
  re-crossmatched back to `MATCHED`.
- U1/U2 tests pass; full suite green in-container; changed files `black`-formatted.
- Idempotency verified (KTD7); recovery introduces no new duplicate publications (R5).
