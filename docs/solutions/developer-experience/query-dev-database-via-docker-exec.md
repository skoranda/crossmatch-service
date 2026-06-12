---
title: "Running ad-hoc SQL against the dockerized dev database"
date: 2026-05-27
category: developer-experience
module: dev-environment
problem_type: developer_experience
component: development_workflow
severity: low
applies_when:
  - "Running ad-hoc SQL or inspecting tables in the local dev database"
  - "A host-side psql connection to 127.0.0.1:5432 fails or psql is not installed"
  - "Writing or verifying a query before wiring it into application code"
tags:
  - dev-environment
  - postgres
  - docker-compose
  - psql
  - database-access
---

# Running ad-hoc SQL against the dockerized dev database

## Context

The dev database is not reachable from the host the way you might expect. It runs as the `django-db` service in `docker/docker-compose.yaml` (Postgres 18.x; under the default compose project the container is `crossmatch-django-db-1`). That service exposes `5432/tcp` **only on the compose network** — it is **not** published to a host port. So from the host:

- `psql -h 127.0.0.1 -p 5432 …` connects to nothing — there is no host port mapping.
- `psql` / `pg_isready` may not even be installed on the host, and there is no `kubectl` context for the dev stack.

The reliable path is to run `psql` **inside** the database container (or via `docker compose exec`), where it talks to the local socket. The connection parameters come from the compose env (defaults below), not from any host config.

## Guidance

Prerequisite: the dev stack must be running (`docker compose -f docker/docker-compose.yaml up -d`). If `docker ps` shows no `django-db` container, start it first.

Credentials are the compose values in `docker/docker-compose.yaml`, env-overridable. Defaults:

- database: `scimma_crossmatch_service` (`DATABASE_DB`)
- user: `crossmatch_service_admin` (`DATABASE_USER`)
- password: `password` (`DATABASE_PASSWORD`) — local dev default; do not treat as a secret or copy elsewhere

Prefer the **service-name** invocation — it does not hardcode the compose-generated container name:

```bash
# Interactive shell
docker compose -f docker/docker-compose.yaml exec django-db \
  psql -U crossmatch_service_admin -d scimma_crossmatch_service

# One-shot query, pager disabled (good for non-interactive / piping)
docker compose -f docker/docker-compose.yaml exec django-db \
  psql -U crossmatch_service_admin -d scimma_crossmatch_service \
  -P pager=off -c "SELECT count(*) FROM catalog_matches;"
```

Equivalent with the literal container name (works from any directory, but the name is project-dependent):

```bash
docker exec -it crossmatch-django-db-1 \
  psql -U crossmatch_service_admin -d scimma_crossmatch_service
```

Useful `psql` flags for scripting:

- `-P pager=off` — never invoke a pager (large result sets won't hang a non-interactive shell).
- `-tA` — tuples-only, unaligned — clean output for piping into other tools.
- `-c "…"` — run one statement and exit; `-f file.sql` — run a file (copy the file into the container or pipe via stdin).

Alternative: from inside any Django app container, `python crossmatch/manage.py dbshell` opens the same `psql` using Django's `DATABASES['default']` settings — handy when you want Django's resolved connection rather than retyping flags.

## Why This Matters

Without this, the obvious moves all dead-end: a host `psql` isn't installed, `127.0.0.1:5432` has nothing listening, and there's no kube context — so it's easy to conclude the DB is unreachable when it's simply network-isolated to the compose stack. Running `psql` inside the container is the one path that just works, and the credentials live in the compose file, not in any host environment.

## When to Apply

- Inspecting or counting rows in the dev DB (e.g. `catalog_matches`, `alert_deliveries`) while developing or debugging.
- Prototyping a query before embedding it in a Django ORM call or a migration.
- Any time a host-side DB connection attempt fails because the port isn't published.

## Examples

Verified this session — count distinct matched objects and per-catalog match rows:

```bash
docker exec crossmatch-django-db-1 \
  psql -U crossmatch_service_admin -d scimma_crossmatch_service -P pager=off -c "
SELECT catalog_name, COUNT(*) AS match_rows,
       COUNT(DISTINCT lsst_diaobject_diaobjectid) AS distinct_objects
FROM catalog_matches
GROUP BY catalog_name
ORDER BY match_rows DESC;"
```

Script-friendly single value (tuples-only, unaligned):

```bash
docker compose -f docker/docker-compose.yaml exec django-db \
  psql -U crossmatch_service_admin -d scimma_crossmatch_service \
  -tA -c "SELECT count(DISTINCT lsst_diaobject_diaobjectid) FROM catalog_matches;"
```

Note: the FK column on `catalog_matches` / `alert_deliveries` is the lowercase `lsst_diaobject_diaobjectid` (the model's `db_column`), not the camelCase Python attribute.

## Related

- `docker/docker-compose.yaml` — the `django-db` service definition and the `DATABASE_*` env defaults used above.
- `crossmatch/project/settings.py` — `DATABASES['default']`, which reads the same `DATABASE_*` env vars (so `manage.py dbshell` resolves to this connection).
