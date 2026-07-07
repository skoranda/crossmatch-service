# Concepts

Shared domain vocabulary for this project — entities, named processes, and status
concepts with project-specific meaning. Seeded with core domain vocabulary, then
accretes as ce-compound and ce-compound-refresh process learnings; direct edits are
fine. Glossary only, not a spec or catch-all.

## Auth gate (operator surfaces)

### Operator surface
An internal, ops-facing web UI exposed for running the service — the Grafana monitoring
dashboards and the Flower Celery dashboard. Operator surfaces are gated behind per-user
authentication; they are not public and are not part of the science data path.

### Gate
The per-user authentication layer in front of the operator surfaces: a single
oauth2-proxy acting as an OIDC client of CILogon, enforced at the edge by Traefik
forwardAuth. "Behind the gate" means a request must carry a valid, authorized session
to reach the surface.

### Auth host
The dedicated hostname that serves the oauth2-proxy sign-in, callback, and auth-check
endpoints for the Gate. It is a distinct host from the surfaces it protects, so one
oauth2-proxy and one OIDC client can front several surfaces.

### Roster
The allowlist of people authorized to pass the Gate, expressed as a list of CILogon
subject identifiers. Authorization keys on the subject (the stable CILogon User
Identifier) and never on email, which upstream federations can reassign. Authentication
succeeds for any CILogon user; the Roster is what grants access.
