---
date: 2026-03-03
topic: fix periodic task module path after tasks.tasks deletion
branch: refactor/align-skeleton-to-design
---

# Brainstorm: Fix Periodic Task Module Path

## What We're Building

A two-line fix to `initialize_periodic_tasks.py` that corrects stale `tasks.tasks`
references left over from when `tasks/tasks.py` was deleted.

## Current State

`initialize_periodic_tasks.py` contains:

```python
from tasks.tasks import periodic_tasks          # line 4  — broken import
...
'task': f'tasks.tasks.{periodic_task.task_handle}',  # line 20 — wrong path written to DB
```

`tasks/tasks.py` was deleted in the previous commit. `periodic_tasks` already lives in
`tasks/schedule.py` (line 43). The management command therefore crashes on import and,
if it had run previously, left a stale `task='tasks.tasks.query_heroic'` DB record in
`django_celery_beat`. Celery-beat raises `KeyError: 'tasks.tasks.query_heroic'` when it
tries to dispatch that record because no task is registered under that name.

## Why This Approach

Fix both references in the one file that owns them. Re-running
`initialize_periodic_tasks` after the code fix will also repair the DB record via
`update_or_create`, so no separate migration is needed.

## Key Decisions

1. **Import source**: `from tasks.schedule import periodic_tasks`
2. **Task path string**: `f'tasks.schedule.{periodic_task.task_handle}'`
3. **DB repair**: re-run `python manage.py initialize_periodic_tasks` after deploy

## Files to Change

| File | Change |
|---|---|
| `crossmatch/project/management/commands/initialize_periodic_tasks.py` | Fix import (line 4) and task path string (line 20) |

## Open Questions

None — scope is clear.
