---
title: "Broker consumers wedge on \"the connection is closed\" because the management-command loop never recycles the DB connection"
date: 2026-07-10
category: docs/solutions/runtime-errors/
module: crossmatch/brokers
problem_type: runtime_error
component: background_job
symptoms:
  - "Consumer logs `Error consuming Lasair alert: the connection is closed` (and the antares/pittgoogle equivalents) once per backoff cycle, forever, at a fixed ~60s cadence"
  - "`django.db.utils.OperationalError: the connection is closed` (psycopg3) from ORM calls inside brokers.ingest_alert"
  - "Consumer pod stays Running with 0 restarts while ingest is fully wedged; a fresh psycopg connect from inside the same pod succeeds"
root_cause: missing_workflow_step
resolution_type: code_fix
severity: high
related_components: [database]
tags: [django, database, psycopg, close-old-connections, conn-health-checks, kafka-consumer, management-command, long-running-process]
---

# Broker consumers wedge on "the connection is closed" because the management-command loop never recycles the DB connection

## Problem
The broker consumers (`lasair`, `antares`, `pittgoogle`) run as long-lived Django
management-command loops (`run_*_ingest`) that call the shared
`brokers.ingest_alert`. After Postgres severed the process's cached DB
connection, every subsequent ingest raised psycopg's "the connection is closed"
and never recovered, silently halting alert ingest across all three brokers
until the pods were restarted.

## Symptoms
- `Error consuming Lasair alert: the connection is closed` logged once per backoff cycle, indefinitely, at a fixed ~60s cadence (the capped backoff `_BACKOFF_MAX`). The steady cadence is the tell that `poll()` returns immediately and the failure is downstream, not in Kafka.
- `django.db.utils.OperationalError: the connection is closed` raised from `Alert.objects.get_or_create` / `AlertDelivery.objects.get_or_create` inside `ingest_alert`.
- All three consumers affected identically (shared ingest path), while the pods stayed `Running` with 0 restarts and a fresh `psycopg.connect()` from inside the pod succeeded — proving the DB was healthy and the connection was individually dead-and-cached.

## What Didn't Work
- Reading the error as a Kafka/broker fault. `confluent_kafka.poll()` reports transport errors via `msg.error()`, never by raising the natural-language string "the connection is closed" — that wording is psycopg3's, so the failure is in the DB path, not the consumer's Kafka client.
- Waiting for self-recovery. The consumer's `try/except` catches the exception, logs, sleeps, and loops — but never resets the connection and never crashes, so the process holds the dead connection forever. Only a pod restart (new process, new connection) cleared it.

## Solution
Recycle the DB connection per unit of work at the shared choke point, mirroring
what Django does per HTTP request and Celery does per task. In
`crossmatch/brokers/__init__.py`, at the top of `ingest_alert`:

```python
from django.db import close_old_connections, connection

def ingest_alert(canonical: dict, broker: str) -> bool:
    # Recycle per work unit; the consumers run outside any request/task
    # lifecycle, so nothing else drops a stale/dead connection. Skip while a
    # transaction is open -- closing mid-transaction would abort it.
    if not connection.in_atomic_block:
        close_old_connections()
    ...
```

Pair it with health-checked, reusable connections in
`crossmatch/project/settings.py` so a healthy connection is validated and reused
rather than reopened on every alert (keeping the ingest hot path cheap) while a
severed one is transparently reconnected:

```python
DATABASES = {
    'default': {
        # ...
        'CONN_MAX_AGE': int(os.getenv('CONN_MAX_AGE', '60')),
        'CONN_HEALTH_CHECKS': True,
    },
}
```

Note: `close_old_connections()` alone fixes correctness; `CONN_HEALTH_CHECKS` +
`CONN_MAX_AGE` avoid reconnecting on every alert. Already-wedged pods must be
restarted to pick up the fix — it prevents recurrence and enables auto-recovery
going forward, but does not resurrect a process already holding a dead
connection.

## Why This Works
Django recycles broken/obsolete connections only via `close_old_connections()`,
which is wired to the `request_started` / `request_finished` signals (and, for
Celery, `task_prerun` / `task_postrun`). A bare management-command loop fires
none of those signals, so the process opens one connection on first query and
reuses it for its lifetime. When the server severs it, psycopg3 marks it closed
and Django keeps handing back the dead handle. Calling `close_old_connections()`
at the top of each ingest restores the missing lifecycle step: with
`CONN_HEALTH_CHECKS` on, a reused connection is pinged and transparently
reopened if dead; when a prior query already errored, the dead connection is
dropped and the next query reconnects. The `in_atomic_block` guard ensures a
connection is never closed while a transaction is open on it. The smoking-gun
confirmation: Celery workers on the same database stayed healthy throughout,
because Celery recycles connections per task and the consumers did not.

## Prevention
- Any new long-running Django loop that touches the ORM outside the request/task lifecycle (Kafka/pub-sub consumers, pollers, daemons, custom `manage.py` commands) must recycle connections per work unit with `close_old_connections()`. Route ORM writes through a shared helper (as the brokers do via `ingest_alert`) so the recycle lives in exactly one place.
- Keep `CONN_HEALTH_CHECKS = True` set so reused connections self-heal after a server-side disconnect.
- Regression test: `crossmatch/tests/test_ingest.py::test_ingest_recovers_from_severed_connection` severs the socket behind Django's back (`connection.connection.close()`) under `@pytest.mark.django_db(transaction=True)` — no wrapping atomic block, matching the consumers' autocommit context — then asserts the next `ingest_alert` succeeds. Verified the same setup raises "the connection is closed" without the fix.

## Related Issues
- Fixed in commit `0bb9804` on branch `fix/consumer-db-connection-recycle` (origin PR #11).
- `docs/solutions/developer-experience/query-dev-database-via-docker-exec.md` — reaching the dev Postgres to confirm DB health during this kind of investigation.
