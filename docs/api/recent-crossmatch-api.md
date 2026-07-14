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

On DEV this endpoint is **public and unauthenticated** by design (a per-page
object cap and a maximum window span bound the work any one request can trigger;
total iteration across pages is intentionally unbounded, with rate limiting
deferred). Do not assume that posture on any future non-DEV deployment.

Results are **keyset (cursor) paged**: each response returns one operator-bounded
page plus an opaque `next_cursor`; following the cursor to exhaustion returns the
window's entire distinct set of matched objects. There is no total-object cap and
no "jump to page N" — see [Paging](#paging).

## Query parameters

All parameters are optional.

| Param | Type | Default | Meaning |
|---|---|---|---|
| `start` | ISO-8601 timestamp (UTC) | `end` minus 12 hours | Window start (inclusive). A value with no timezone offset is interpreted as UTC. |
| `end` | ISO-8601 timestamp (UTC) | now | Window end (exclusive). |
| `time_field` | `ingest_time` \| `event_time` | `ingest_time` | Which alert timestamp the window filters on. `ingest_time` is when the alert arrived at the service; `event_time` is the observation/candidate time. |
| `detail` | `ids` \| `position` \| `matches` \| `full` | `matches` | How much per-object and per-match data to return (cumulative; see below). |
| `page_size` | positive integer | 1000 | Maximum number of objects in the page. A value above the operator maximum is **clamped down**, not rejected. |
| `cursor` | opaque string | none | A `next_cursor` from a prior page. Resumes the next page. It **pins** `start`/`end`/`time_field`/`detail`; see [Paging](#paging). |

### Bounds

- **Default page size:** 1000 (`RECENT_CROSSMATCH_DEFAULT_PAGE_SIZE`), used when
  `page_size` is omitted.
- **Maximum page size:** 10000 (`RECENT_CROSSMATCH_MAX_PAGE_SIZE`). A `page_size`
  larger than this is clamped, not rejected.
- **No total-object cap:** there is no limit on how many objects a window can be
  paged through in total; only per-page size is bounded.
- **Maximum window span:** 168 hours (7 days; `RECENT_CROSSMATCH_MAX_WINDOW_HOURS`).
  A `start`/`end` span longer than this returns `400`.

### Errors

Any invalid parameter returns HTTP `400` with a JSON body `{"error": "<reason>"}`:
an unknown `detail` or `time_field`, an unparseable `start`/`end`, a
non-positive or non-integer `page_size`, a malformed `cursor`, a `cursor`
presented with a conflicting `start`/`end`/`time_field`/`detail`, an `end`
earlier than `start`, or a window span beyond the maximum. A non-`GET` method
returns `405`.

## Response

Always a JSON object with the resolved query metadata, paging fields, and an
`objects` list. The result is **matches-only**: an object whose alert is in the
window but that has no catalog match is not included.

```json
{
  "window": {"start": "2026-07-13T00:00:00+00:00", "end": "2026-07-13T12:00:00+00:00"},
  "time_field": "ingest_time",
  "detail": "matches",
  "page_size": 1000,
  "count": 2,
  "next_cursor": "eyJ0IjoiMjAy...",
  "objects": [ ... ]
}
```

- `page_size` is the effective page size used (after clamping/defaulting).
- `count` is the number of objects **on this page**, not a whole-set total (no
  cheap total exists under keyset paging).
- `next_cursor` is the opaque token to fetch the next page, or `null` when the
  window is exhausted.

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

## Paging

Results are ordered **newest-first** by the selected `time_field`, with
`diaObjectId` as a unique tiebreaker. Each page returns a `next_cursor`; pass it
back as `cursor` to fetch the next page, and stop when `next_cursor` is `null`.
The union of all pages is the window's entire distinct set of matched objects,
each `diaObjectId` appearing exactly once.

- **The cursor is opaque.** Treat it as a token; do not parse or construct it. It
  is `base64url`-encoded and unsigned (it carries only public query parameters and
  a public sort position).
- **The cursor pins the query.** It records the `start`, `end`, `time_field`, and
  `detail` it was issued for. You may omit those params on the follow-up request
  (they are derived from the cursor) or repeat the same values, but presenting a
  **different** value for any of them returns `400` — this prevents a paged walk
  from silently drifting to a different query. `page_size` is **not** pinned and
  may change from page to page.
- **Stability.** A walk is duplicate-free: an object already returned is never
  returned again. For a **closed window** (e.g. last night, observing finished)
  or any window walked by **`ingest_time`** (the default), the walk is also a
  consistent snapshot — objects inserted while you page do not appear mid-walk.
  The one exception is an **open/rolling window walked by `event_time`**:
  `event_time` is the observation time, not the insertion time, so an alert
  ingested mid-walk can carry an `event_time` earlier than your current position
  and may appear (never as a duplicate). For an exact "pull the whole set",
  page a closed window.

## Examples

Last 12 hours (defaults), grouped by object with catalog/source/separation:

```
GET /api/recent-crossmatches
```

An explicit window on observation time, ids only:

```
GET /api/recent-crossmatches?start=2026-07-12T00:00:00Z&end=2026-07-13T00:00:00Z&time_field=event_time&detail=ids
```

Full published payload, 200 objects per page:

```
GET /api/recent-crossmatches?detail=full&page_size=200
```

Walk an entire window (follow `next_cursor` until it is `null`):

```
GET /api/recent-crossmatches?time_field=event_time&detail=ids&page_size=1000
  -> {"...": "...", "next_cursor": "eyJ0Ijoi...", "objects": [ ... ]}
GET /api/recent-crossmatches?cursor=eyJ0Ijoi...
  -> {"...": "...", "next_cursor": "eyJ0Ijoi...", "objects": [ ... ]}
...
GET /api/recent-crossmatches?cursor=<last>
  -> {"...": "...", "next_cursor": null, "objects": [ ... ]}   # done
```

A runnable end-to-end example lives in
[`notebooks/recent_crossmatch_demo.ipynb`](../../notebooks/recent_crossmatch_demo.ipynb).
