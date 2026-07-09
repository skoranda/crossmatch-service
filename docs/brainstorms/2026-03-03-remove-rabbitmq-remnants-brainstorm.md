---
date: 2026-03-03
topic: remove all RabbitMQ code and references
branch: refactor/align-skeleton-to-design
---

# Brainstorm: Remove RabbitMQ Code and References

## What We're Building

A cleanup pass that removes every RabbitMQ-specific string, variable, and Helm template from
the codebase, replacing them with the Valkey/Redis equivalents that are already used in
`settings.py` and `values.yaml`.

## Current State

The codebase is partially migrated. Three distinct categories of RabbitMQ remnants remain:

**1. Dead Python code (`celery.py` lines 7–10)**
```python
rabbitmq_username = os.environ.get('RABBITMQ_DEFAULT_USER', 'rabbitmq')
rabbitmq_password = os.environ.get('RABBITMQ_DEFAULT_PASS', 'rabbitmq')
rabbitmq_service  = os.environ.get('MESSAGE_BROKER_HOST', 'rabbitmq')
rabbitmq_port     = os.environ.get('MESSAGE_BROKER_PORT', '5672')
```
These variables are never used — the broker URL comes from `CELERY_BROKER_URL` in
`settings.py` (which already uses `VALKEY_*` vars).

**2. Broken Helm template (`_helpers.yaml` + `statefulset.yaml`)**
`_helpers.yaml` still defines `rabbitmq.env` which references `Values.rabbitmq.*`.
`values.yaml` has no `rabbitmq` section → Helm rendering would fail.
`statefulset.yaml` includes `rabbitmq.env` in three places (alert-consumer, worker, beat).

**3. Env var naming mismatch across layers**
`settings.py` uses `VALKEY_SERVICE` / `VALKEY_PORT`.
Entrypoints and docker-compose use `MESSAGE_BROKER_HOST` / `MESSAGE_BROKER_PORT`.
In Kubernetes, nothing injects `MESSAGE_BROKER_*`, so wait-for-it would fall back to
incorrect defaults. This must be harmonised as part of the same cleanup.

## Why This Approach

Replace the `rabbitmq.env` Helm helper with a `valkey.env` helper (using `VALKEY_SERVICE` /
`VALKEY_PORT`) to match `settings.py`. Simultaneously update entrypoints and docker-compose
to use the same `VALKEY_*` naming so all three deployment layers are consistent.

## Key Decisions

1. **Helm helper name**: `rabbitmq.env` → `valkey.env`
2. **Helm helper env vars**: `VALKEY_SERVICE` (from `Values.valkey.fullnameOverride`) +
   `VALKEY_PORT` (hardcoded `"6379"`)
3. **Entrypoints**: `${MESSAGE_BROKER_HOST}:${MESSAGE_BROKER_PORT}` → `${VALKEY_SERVICE:-redis}:${VALKEY_PORT:-6379}`
4. **docker-compose**: Replace `MESSAGE_BROKER_HOST/PORT` env vars with `VALKEY_SERVICE/VALKEY_PORT`;
   update valkey service network alias accordingly
5. **`celery.py`**: Remove the four dead `rabbitmq_*` variable lines entirely

## Files to Change

| File | Change |
|---|---|
| `crossmatch/project/celery.py` | Delete lines 7–10 (unused rabbitmq vars) |
| `crossmatch/entrypoints/run_celery_worker.sh` | `MESSAGE_BROKER_*` → `VALKEY_*` |
| `crossmatch/entrypoints/run_celery_beat.sh` | `MESSAGE_BROKER_*` → `VALKEY_*` |
| `crossmatch/entrypoints/run_flower.sh` | `MESSAGE_BROKER_*` → `VALKEY_*` |
| `crossmatch/entrypoints/run_alert_consumer.sh` | `MESSAGE_BROKER_*` → `VALKEY_*` |
| `docker/docker-compose.yaml` | Replace `MESSAGE_BROKER_*` with `VALKEY_*` everywhere |
| `kubernetes/.../templates/_helpers.yaml` | Remove `rabbitmq.env`, add `valkey.env` |
| `kubernetes/.../templates/statefulset.yaml` | 3× `rabbitmq.env` → `valkey.env` |

## Open Questions

None — scope is well-defined and all decisions are made.
