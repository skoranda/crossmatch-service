---
date: 2026-06-30
topic: alert-payload-retention
---

# Alert payload retention and disk guardrail — requirements

## Summary

Add a retention policy that drops the raw `core_alert.payload` (and the
duplicate `core_notification.payload`) once an alert/notification has been
terminal for a configurable grace period, keeping the rows themselves. Pair it
with a one-time reclaim of the space already consumed and a disk-usage guardrail
that warns before the volume fills again. All tunables are configurable through
the existing chart-value → env → Django settings mechanism with sane defaults.

## Problem Frame

The DEV `django-db` 5Gi PVC filled in ~22h of alert ingestion and crash-looped
Postgres on a full volume (`No space left on device` during the end-of-recovery
checkpoint), taking the database and every DB-dependent pod down. The volume was
expanded to 50Gi as a stopgap.

~90% of the database is the TOASTed raw `core_alert.payload` JSON: ~4 GB across
~535k alerts (~8 KB each), ingested from three brokers (antares, lasair,
pittgoogle) at roughly 535k alerts/day. Every alert in the DB was less than a day
old, so the problem is raw throughput, not accumulated history — age-based
deletion of old records would free nothing. The raw payload is read only while an
alert is in flight (to build the notification at crossmatch time); nothing reads
it after the alert reaches NOTIFIED. The payload is effectively stored twice: the
notification carries its own published-form payload copy, which is dead weight
once the notification is SENT.

## Key Decisions

- **Drop payloads, keep the rows.** Nulling the bulky JSON caps ~90% of growth
  while preserving the alert/notification/match rows, so ingest deduplication and
  match history stay intact. Deleting rows would put both at risk and is deferred.
- **Drop after a grace period, not immediately.** Payloads are dropped only once
  the alert/notification has been terminal for a configurable grace period
  (default in the 1–3 day range), leaving headroom to inspect or debug recent
  alerts. Steady-state payload footprint is roughly the grace period's worth of
  ingestion (~6–12 GB at current rates).
- **Anchor the grace period on terminal time.** The grace period is measured from
  when the alert actually became NOTIFIED — via a new `notified_at` timestamp set
  on that transition — and from `sent_at` for notifications, rather than from
  ingest time. This is precise at the cost of a small schema addition.
- **Null in place, do not archive.** The raw payload is disposable after
  processing — the result is captured in `catalog_matches` and `core_notification`
  — so there is no archive-to-object-store step.
- **Everything tunable is configurable with a sane default.** Grace period,
  guardrail thresholds, and task cadence are set through the existing
  values → env → settings path (the same mechanism as `CROSSMATCH_BATCH_MAX_SIZE`
  et al.), never hardcoded.
- **Guardrail is net-new and lightweight.** There is no existing metrics
  infrastructure (`prometheus-client` is a dependency but unused), so the
  guardrail is a simple DB/PVC-size threshold check that emits a warning, not a
  full metrics exporter.

## Requirements

**Payload retention**

- R1. A periodic task drops `core_alert.payload` for alerts whose `notified_at` is
  older than a configurable grace period.
- R2. The same retention drops `core_notification.payload` for notifications whose
  `sent_at` is older than the grace period.
- R3. `Alert` gains a `notified_at` timestamp, set when the alert transitions to
  NOTIFIED, to anchor R1's grace period.
- R4. `core_alert.payload` and `core_notification.payload` become nullable so the
  payload can be cleared without deleting the row (both are currently
  `NOT NULL`).
- R5. Dropping a payload must not alter the row's identity or lifecycle state, and
  must leave ingest deduplication and existing `catalog_matches` / notification
  records unaffected.
- R6. The retention task is idempotent and safe to run repeatedly — already-cleared
  rows are skipped, and a run must not block or starve ingestion/crossmatch/notify
  work.

**Reclaim and backfill**

- R7. At migration time, bring already-terminal rows under retention: backfill
  `notified_at` for existing NOTIFIED alerts (a NULL `notified_at` is never caught
  by R1) and clear payloads for alerts/notifications already past the grace
  period. Without this, the ~535k pre-existing rows keep their payloads forever
  and the reclaim below has nothing to free.
- R8. Provide a one-time reclaim that returns the ~4 GB already occupied by dead
  payloads to the operating system (plain autovacuum reuses space within the
  table but does not shrink the files on disk).

**Disk guardrail**

- R9. A guardrail warns when database or PVC usage crosses a configurable
  threshold and routes the warning to an actionable channel — not just a log line,
  since there is no existing alerting infrastructure — so an approaching
  full-volume condition is acted on before it causes an outage.

**Configuration**

- R10. All tunables — grace period, guardrail threshold(s), and task cadence(s) —
  are exposed through the existing chart-value → environment-variable → Django
  settings path with sane defaults, consistent with the current
  `CROSSMATCH_BATCH_*` settings.

## Acceptance Examples

- AE1. **Covers R1, R5.** An alert's `notified_at` is older than the grace period
  → its `payload` is cleared on the next retention run; its status,
  `catalog_matches`, and notification rows are unchanged.
- AE2. **Covers R1.** An alert's `notified_at` is more recent than the grace
  period → its `payload` is retained.
- AE3. **Covers R1, R5.** An alert is still INGESTED, QUEUED, or MATCHED (not
  terminal, so `notified_at` is unset) → its `payload` is retained regardless of
  age, so in-flight crossmatch/notify still has it.
- AE4. **Covers R2.** A notification is SENT longer ago than the grace period →
  its `payload` is cleared; a PENDING/FAILED notification keeps its payload so it
  can still be published or retried.
- AE5. **Covers R6.** A retention run over alerts whose payloads were already
  cleared makes no changes and completes without disrupting concurrent ingestion.
- AE6. **Covers R9.** Usage crosses the configured threshold → a warning is
  emitted; below the threshold → no warning.

## Scope Boundaries

**Deferred for later**

- Row age-out — deleting terminal alerts and their `core_notification`,
  `catalog_matches`, and `alert_deliveries` children after a retention window. The
  skinny rows still grow (~1 GB/day) with payloads dropped, so the 50Gi volume
  fills in roughly 5–6 weeks (~38–44 GB free at ~1 GB/day); the guardrail (R9) is
  the interim safety net, and row age-out should start before that projected fill
  date rather than waiting for the warning. Row deletion needs explicit handling
  of ingest deduplication and FK cascade behavior. Row age-out also covers
  permanently-FAILED notifications, whose payloads R2's `sent_at` path never
  clears.

**Out of scope**

- Archiving payloads to object storage (e.g. S3 via `s3fs`) — rejected because
  payloads are disposable after processing.
- Reducing per-alert payload size at ingestion (trimming fields, compression
  changes) — separate concern from retention.

## Dependencies / Assumptions

- Assumes nothing reads `core_alert.payload` after NOTIFIED nor
  `core_notification.payload` after SENT — verified against the current code, but
  any future consumer of post-terminal payloads would conflict with this policy.
- The cinder StorageClass allows volume expansion (already confirmed during the
  incident), but retention is what bounds growth; expansion is not a substitute.
- This policy targets DEV initially. Whether it applies to PROD — with the same
  grace/threshold defaults or environment-specific ones — and whether PROD carries
  a reproducibility/audit retention requirement that conflicts with null-in-place
  must be decided before enabling it there.

## Outstanding Questions

**Deferred to planning**

- Reclaim mechanism: `VACUUM FULL` (simple, takes an exclusive lock — acceptable
  in DEV during a quiet window) vs `pg_repack` (online, no long lock, needs the
  extension installed). Choose during planning per environment.
- Default values for the grace period and guardrail threshold(s), and the
  retention/guardrail task cadence.
- Guardrail signal mechanism (log warning, structlog event, beat task that
  queries DB size) and where the threshold is measured (Postgres database size vs
  PVC filesystem usage).

## Sources / Research

- Incident table sizes (live DEV, 2026-06-30): `core_alert` 4513 MB total
  (4038 MB TOAST payload, ~495k–535k rows); `core_notification` 233 MB;
  `catalog_matches` 192 MB; `alert_deliveries` 121 MB.
- `crossmatch/core/models.py` — `Alert.payload` and `Notification.payload` are
  `JSONField(null=False)`; `Alert` timestamps are `event_time` + `ingest_time`
  (auto_now_add); `Notification` has `sent_at`. Alert status state machine
  INGESTED → QUEUED → MATCHED → NOTIFIED.
- `crossmatch/tasks/crossmatch.py` builds the notification payload from the alert
  payload at crossmatch time; `crossmatch/notifier/impl_hopskotch.py` publishes
  `notif.payload`. No code reads `alert.payload` after NOTIFIED.
- `crossmatch/tasks/schedule.py` — existing periodic-task pattern
  (`dispatch_crossmatch_batch`, `dispatch_notifications`) to mirror for the
  retention/guardrail task; `crossmatch/project/settings.py` `CROSSMATCH_BATCH_*`
  for the configuration pattern.
- No existing retention/cleanup tasks; `prometheus-client` is a dependency but
  has no current usage.
