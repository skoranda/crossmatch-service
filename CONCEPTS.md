# Concepts

Shared domain vocabulary for this project — entities, named processes, and status
concepts with project-specific meaning. Seeded with core domain vocabulary, then
accretes as ce-compound and ce-compound-refresh process learnings; direct edits are
fine. Glossary only, not a spec or catch-all.

## Crossmatch domain

### Crossmatch
The core operation, and the service itself: matching each incoming Alert's sky position
against astronomical source catalogs to find known sources nearby. The match is purely
positional — coordinates within a fixed angular radius — not based on brightness, color,
or time.

### Alert
A transient-source detection ingested from a Broker, carrying a sky position (right
ascension and declination, in degrees) and a Rubin object identifier. Alerts are the
input stream the service crossmatches and publishes results for.

### Broker
An upstream service that delivers the Vera C. Rubin Observatory alert stream — ANTARES,
Lasair, and Pitt-Google. Each Broker has its own ingestion and normalization path that
maps its wire format onto the common Alert shape.

### HATS catalog
A large astronomical source catalog stored in HATS (Hierarchical Adaptive Tiling Scheme)
format and queried via LSDB on the Dask cluster — Gaia DR3, DES Y6 Gold, DELVE DR3 Gold,
and SkyMapper DR4. Column naming is inconsistent across catalogs: some lowercase, some
uppercase, and SkyMapper coordinates carry a J2000 suffix.

### Match
A catalog source found within the crossmatch radius of an Alert, together with its
angular separation. The Match is the unit of result the service produces.

### Payload
The per-Match JSON record published to the public astronomy community over Hopskotch. It
is built from a per-catalog selection of catalog columns, with values coerced from
catalog/dataframe types to JSON-native ones and keys normalized to a stable form.

### diaObjectId
The Rubin identifier of an Alert's source object: a 64-bit integer that must be carried
as int64 end to end and coerced explicitly before JSON, never allowed to round-trip
through a float.

### Hopskotch
The SCiMMA Kafka-based distribution service over which the service publishes Payloads to
the public astronomy community.

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
