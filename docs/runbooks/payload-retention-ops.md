# Payload Retention — Operational Runbook (reclaim + guardrail)

Operational steps for the payload-retention feature (U6 reclaim, U7 guardrail). The
app-code half (schema, anchor, sweep, config, backfill) ships in the retention PR;
this runbook covers the parts an operator runs. Plan of record:
`docs/plans/2026-07-21-002-feat-alert-payload-retention-plan.md`.

## What the app ships

- `Alert.notified_at` (terminal-completion anchor), nullable payload columns
  (migration `0006`), the concurrent `notified_at` index (`0007`), and the
  `notified_at` backfill (`0008`).
- A `retention_sweep` Celery Beat task that nulls terminal payloads past the grace,
  bounded by `CROSSMATCH_RETENTION_MAX_ROWS` per run.
- Config: `CROSSMATCH_RETENTION_GRACE_DAYS` (default 30), `_MAX_ROWS` (10000),
  `_INTERVAL_SECONDS` (3600). **DEV overrides the grace to ~3 days** via
  `values-dev.yaml` in the gitops repo (a separate commit — DEV's ~56 KB payloads
  fill any 30-day window long before 30 days).

## U6 — one-time reclaim

Nulling a payload marks the row dead but does not shrink the table files; a reclaim
returns the space to the OS.

**DEV (do now).** DEV is ~60% full and ~94% payload, ingestion is paused. After the
migration backfills `notified_at` and the sweep has nulled payloads past the (short)
DEV grace, run in the paused-ingest window:

```sql
VACUUM FULL core_alert;
VACUUM FULL core_notification;
```

`VACUUM FULL` takes an `ACCESS EXCLUSIVE` lock — acceptable on DEV precisely because
ingest is paused. Expect a large drop (60% -> ~15%). Verify with `df -h
/var/lib/postgresql/data` inside the `django-db` pod.

**PROD (deferred).** PROD's data is all <30 days old, so nothing is past the 30-day
grace yet and there is **no dead payload to reclaim at cutover** — the reclaim is a
no-op today. Once PROD payload accumulates past 30 days and the sweep starts nulling
it, choose an **online** reclaim (`pg_repack`, which requires installing the
extension — a dependency-pin/infra change) to avoid a long exclusive lock on the live
public service. Do **not** run `VACUUM FULL` on live PROD.

## U7 — disk guardrail (specified here, applied in gitops)

The guardrail is a Prometheus/Grafana alert in the monitoring stack (both envs run
it). No app-side metric is required: kubelet already exports PVC usage
(`kubelet_volume_stats_used_bytes` / `kubelet_volume_stats_capacity_bytes`) for the
`django-db-data` PVC. Add these alert rules in the gitops monitoring stack (separate
commit):

- **Primary — usage threshold (both envs):** warn when
  `kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes` for the
  `django-db-data` PVC crosses a configurable threshold (e.g. 0.75), so an
  approaching full volume is acted on before an outage.
- **Early warning — grace vs measured fill-time:** warn when the configured grace
  approaches or exceeds the **measured** fill-time (free bytes / current growth rate
  derived from `predict_linear` on the PVC usage series) — the condition where
  retention frees nothing (the DEV failure). Keying on the *measured* rate is what
  catches the 30-day PROD default silently becoming unsafe as the Rubin alert rate
  rises.

Route both to an actionable channel (not just a Grafana panel).

## Rollback caveat (migration 0006 is irreversible once the sweep runs)

Migration `0006` makes the payload columns nullable. Reversing it emits
`ALTER COLUMN payload SET NOT NULL`, which PostgreSQL rejects once **any** payload is
NULL — i.e. as soon as the retention sweep has cleared one row (PROD ~30 days after
enable, DEV ~3 days). So rollback below `0006` is **unsupported** once the sweep has
run: an emergency downgrade must first re-populate or `DELETE` the null-payload rows.
The data nulling was already permanent (governance decision); this notes that the
*schema* migration is permanent too. (`0008`'s `noop_reverse` leaving `notified_at`
populated is separately fine.)

## Rollout order (per env)

1. Set the grace (DEV 3d via `values-dev.yaml`; PROD inherits 30d), deploy.
2. Migrations apply on startup (`locked_init`) — `0006` metadata-only, `0007`
   concurrent index, `0008` chunked backfill. On a live, actively-ingesting table run
   in a quiet window (the `locked_init` advisory lock serializes ingest behind the
   migrate run).
3. The `retention_sweep` task runs on its interval, nulling past-grace payloads.
4. DEV: run the `VACUUM FULL` reclaim. PROD: reclaim deferred.
5. Add the gitops guardrail alert rules.
