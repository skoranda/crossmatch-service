# Residual Review Findings - feat/alert-payload-retention

Source: `/lfg` ce-code-review (mode:agent) on `feat/alert-payload-retention` at
`9111de1`, plan `docs/plans/2026-07-21-002-feat-alert-payload-retention-plan.md`.

The deploy-blocking finding (data-migration P2: the `0008` `atomic=False` +
streaming `.iterator()` cursor invalidation) and the correctness test-gap findings
were **applied** in the review-followup commit (`9111de1`) and are not listed here.

The findings below are **advisory** (owner: human). They are pre-existing behaviors
the retention feature interacts with, or deliberate scope boundaries settled in the
plan (KTD-level), not regressions introduced by this branch. Recorded here so they
are durable and actionable, not lost.

## Advisory findings (owner: human)

- **P2 / reliability - FAILED notifications are never reclaimed.** The notification
  sweep anchors on `sent_at`, which stays NULL for a notification stuck in `FAILED`
  (there is no `FAILED -> PENDING` requeue in code). Such rows keep their payload
  forever. Bounded in practice (FAILED is rare and already a monitored dead-end), but
  a permanently-failed backlog would not be reclaimed. Follow-up belongs with the
  notification-retry design, not this feature.
  `crossmatch/tasks/retention.py`, `crossmatch/tasks/schedule.py`.

- **P3 / reliability - partial-batch provenance loss compounds with nulling.** Step 4
  wraps each match row defensively and transitions the batch to `MATCHED`
  unconditionally, so a row that fails to build is dropped and its provenance is
  already lost today. Once retention nulls the alert payload past grace, that dropped
  match can no longer be reconstructed from the payload either. Pre-existing behavior
  (see the CLAUDE.md "build match rows per-row defensively" gotcha); retention only
  removes the late reconstruction path. `crossmatch/tasks/crossmatch.py`.

- **P3 / data-migration - `ingest_time` backfill floor is intentionally coarse.** The
  `0008` backfill sets `notified_at = ingest_time` for existing terminal alerts. An
  alert ingested long ago but only recently terminal gets an artificially old anchor
  and is swept on the first post-deploy run. Accepted in the plan (KTD2: `ingest_time`
  is a defensible floor; grace math is dominated by row age; run the backfill in a
  quiet window). Noted so the coarseness is a known, not a surprise.
  `crossmatch/core/migrations/0008_backfill_notified_at.py`.

- **P3 / reliability - `retention_sweep` has a row cap but no statement timeout.** The
  sweep is bounded per run by `CROSSMATCH_RETENTION_MAX_ROWS` (10000) but sets no
  wall-clock / `statement_timeout`. The row cap makes a runaway unlikely; a
  belt-and-suspenders statement timeout on the sweep queries would harden it against a
  pathologically slow DB. `crossmatch/tasks/retention.py`.

- **P3 / performance - step-4 anchor UPDATE marginally extends lock hold.** The new
  `notified_at` UPDATE for the non-matched subset adds one more write inside the
  crossmatch task's step-4 path, marginally extending row-lock hold on the batch. Small
  and on the batch's own rows; called out for completeness.
  `crossmatch/tasks/crossmatch.py`.
