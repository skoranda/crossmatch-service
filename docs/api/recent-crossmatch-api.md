# Recent Crossmatch API

A read-only HTTP endpoint that returns the catalog crossmatches for objects that
had an alert in a recent time window, grouped by object, at a caller-selectable
level of detail. It exists to feed scientist-facing demos and notebooks (for
example, "show me the crossmatches for everything with an alert in the last
night of observing") without a database login.

## Endpoint

```
GET https://crossmatch-dev.scimma.org/api/recent-crossmatches
```

On DEV this endpoint is **public and unauthenticated** by design (a hard
server-side object cap and a maximum window span bound the work any one request
can trigger). Do not assume that posture on any future non-DEV deployment.

## Query parameters

All parameters are optional.

| Param | Type | Default | Meaning |
|---|---|---|---|
| `start` | ISO-8601 timestamp (UTC) | `end` minus 12 hours | Window start (inclusive). A value with no timezone offset is interpreted as UTC. |
| `end` | ISO-8601 timestamp (UTC) | now | Window end (exclusive). |
| `time_field` | `ingest_time` \| `event_time` | `ingest_time` | Which alert timestamp the window filters on. `ingest_time` is when the alert arrived at the service; `event_time` is the observation/candidate time. |
| `detail` | `ids` \| `position` \| `matches` \| `full` | `matches` | How much per-object and per-match data to return (cumulative; see below). |
| `limit` | positive integer | server ceiling | Maximum number of objects to return. A value above the server-side ceiling is **clamped down** to the ceiling, not rejected. |

### Bounds

- **Maximum objects returned:** 500 (server-side ceiling; overridable only by
  operators via `RECENT_CROSSMATCH_MAX_OBJECTS`). A `limit` larger than this is
  clamped, not rejected.
- **Maximum window span:** 168 hours (7 days; `RECENT_CROSSMATCH_MAX_WINDOW_HOURS`).
  A `start`/`end` span longer than this returns `400`.

### Errors

Any invalid parameter returns HTTP `400` with a JSON body `{"error": "<reason>"}`:
an unknown `detail` or `time_field`, an unparseable `start`/`end`, a
non-positive or non-integer `limit`, an `end` earlier than `start`, or a window
span beyond the maximum. A non-`GET` method returns `405`.

## Response

Always a JSON object with the resolved query metadata and an `objects` list. The
result is **matches-only**: an object whose alert is in the window but that has
no catalog match is not included.

```json
{
  "window": {"start": "2026-07-13T00:00:00+00:00", "end": "2026-07-13T12:00:00+00:00"},
  "time_field": "ingest_time",
  "detail": "matches",
  "count": 2,
  "objects": [ ... ]
}
```

Each entry in `objects` grows with the `detail` level. The levels are cumulative:
each includes everything the previous level does.

### `detail=ids`

Object identifiers only:

```json
{"diaObjectId": 9000000123}
```

### `detail=position`

Adds the alert **object** position (`ra`/`dec` in degrees):

```json
{"diaObjectId": 9000000123, "ra": 180.0, "dec": -30.0}
```

### `detail=matches` (default)

Adds a `matches` list. Each match names the catalog, the source id in that
catalog, and the angular separation in arcseconds between the alert object and
the catalog source:

```json
{
  "diaObjectId": 9000000123,
  "ra": 180.0,
  "dec": -30.0,
  "matches": [
    {"catalog_name": "gaia_dr3", "catalog_source_id": "42", "separation_arcsec": 0.5}
  ]
}
```

### `detail=full`

Each match becomes the full published payload — exactly what the service
publishes over Hopskotch for that match, including the nested `catalog_payload`
of catalog-specific columns. Note that `ra`/`dec` inside a match are the matched
**catalog source** coordinates (`source_ra_deg`/`source_dec_deg`), which differ
from the object's `ra`/`dec` at the object level:

```json
{
  "diaObjectId": 9000000123,
  "ra": 180.0,
  "dec": -30.0,
  "matches": [
    {
      "diaObjectId": 9000000123,
      "ra": 180.0011,
      "dec": -29.9998,
      "catalog_name": "gaia_dr3",
      "catalog_source_id": "42",
      "separation_arcsec": 0.5,
      "catalog_payload": {"phot_g_mean_mag": 18.3, "ruwe": 1.02, "...": "..."}
    }
  ]
}
```

Only the current match version per `(object, catalog, source)` is returned, so a
re-matched object surfaces each match once, not once per version.

## Examples

Last 12 hours (defaults), grouped by object with catalog/source/separation:

```
GET /api/recent-crossmatches
```

An explicit window on observation time, ids only:

```
GET /api/recent-crossmatches?start=2026-07-12T00:00:00Z&end=2026-07-13T00:00:00Z&time_field=event_time&detail=ids
```

Full published payload for the last night, capped at 100 objects:

```
GET /api/recent-crossmatches?detail=full&limit=100
```

A runnable end-to-end example lives in
[`notebooks/recent_crossmatch_demo.ipynb`](../../notebooks/recent_crossmatch_demo.ipynb).
