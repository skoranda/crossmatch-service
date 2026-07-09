---
date: 2026-03-03
topic: fix Celery task registration for crossmatch_alert
branch: refactor/align-skeleton-to-design
---

# Brainstorm: Fix Celery Task Registration

## What We're Building

A targeted fix that makes `crossmatch_alert` (and the schedule tasks) visible to the
Celery worker by correcting `CELERY_IMPORTS` in `settings.py`, plus removal of the
superseded `tasks/tasks.py` stub that is no longer dispatched anywhere.

## Current State

`settings.py` has:

```python
CELERY_IMPORTS = [
    "tasks.tasks",
]
```

`tasks/tasks.py` defines a task named `"Crossmatch"` (old stub, expects `alert_id` / `uuid`).
`tasks/crossmatch.py` defines `"crossmatch_alert"` (new task, dispatched by the consumer).
`tasks/schedule.py` defines `"query_heroic"` and `"refresh_planned_pointings"`.

Neither `tasks.crossmatch` nor `tasks.schedule` is in `CELERY_IMPORTS`, so the worker
starts with only the old `"Crossmatch"` task registered and rejects every
`crossmatch_alert` dispatch with:

```
ERROR/MainProcess Received unregistered task of type 'crossmatch_alert'
```

`celery_app.autodiscover_tasks()` is commented out, so auto-discovery won't help.

## Why This Approach

Replace the single-item `CELERY_IMPORTS` list with the three correct modules and delete
the stale `tasks/tasks.py`. No architecture change is needed — the file and task already
exist, they just aren't wired into the imports list.

## Key Decisions

1. **`CELERY_IMPORTS`**: replace `["tasks.tasks"]` with
   `["tasks.crossmatch", "tasks.schedule"]`
2. **Delete `tasks/tasks.py`**: the old `"Crossmatch"` stub is superseded by
   `tasks/crossmatch.py` and is dispatched nowhere — remove it to avoid confusion.

## Files to Change

| File | Change |
|---|---|
| `crossmatch/project/settings.py` | Update `CELERY_IMPORTS` list |
| `crossmatch/tasks/tasks.py` | Delete (stale stub) |

## Open Questions

None — scope is well-defined and all decisions are made.
