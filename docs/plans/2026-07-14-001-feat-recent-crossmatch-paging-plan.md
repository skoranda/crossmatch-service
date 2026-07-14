---
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-brainstorm
execution: code
type: feat
origin: docs/plans/2026-07-13-001-feat-recent-crossmatch-api-plan.md
date: 2026-07-14
---

# Recent Crossmatch API Paging - Plan

## Goal Capsule

- **Objective:** Let a client retrieve the *entire* set of a window's distinct
  diaObjectIds-with-matches from the recent-crossmatch endpoint, one
  operator-bounded page at a time, by replacing the hard total-object cap with
  keyset (cursor) pagination.
- **Product authority:** Maintainer/developer (Scott Koranda).
- **Product Contract preservation:** Unchanged. The two items the brainstorm
  left "Deferred to Planning" (cursor encoding, cursor/query-mismatch handling)
  are resolved in the Planning Contract (KTD2, KTD3), not by changing any R-ID.
- **Open blockers:** None.

---

## Product Contract

### Summary

The recent-crossmatch endpoint currently truncates results at a hard total cap
(`RECENT_CROSSMATCH_MAX_OBJECTS`, 500), so a caller cannot pull a full night
(~117k matched objects last night). Replace that total cap with keyset
pagination: every response returns one operator-bounded page plus a cursor, and
following the cursor to exhaustion returns the whole window's distinct
diaObjectIds-with-matches exactly once.

### Key Decisions

- **KD1 — Keyset (cursor) pagination, not offset.** The endpoint returns an
  opaque `next_cursor`; the client passes it back for the next page. Iteration
  is gap- and duplicate-free even while new alerts land, and stays fast deep in
  the set. The trade-off — no random "jump to page N" and no cheap whole-set
  total — is accepted, because the goal is walking the full set.
- **KD2 — Universal paging with a single operator bound.** The total cap
  `RECENT_CROSSMATCH_MAX_OBJECTS` is retired and replaced by an operator maximum
  page size plus a default page size. Every response is a page; there is no
  server-side total cap on how many objects a window can be paged through.
- **KD3 — Per-page cap is the only safety bound.** Total iteration per client
  stays unbounded; rate limiting and auth remain deferred, consistent with the
  accepted public-on-DEV posture of the endpoint.

### Requirements

**Pagination contract**

- **R1** A response returns at most one page of objects, sized by the caller's
  requested page size clamped to the operator maximum; the default page size
  applies when the caller omits it.
- **R2** A response carries a `next_cursor` the caller passes back to fetch the
  next page; it is null/absent when no further objects remain in the window.
- **R3** Following `next_cursor` to exhaustion returns every distinct
  diaObjectId-with-match in the window exactly once — no duplicates, no skips —
  under the stability guarantee in R11.
- **R4** A request with no paging parameters returns the first default-sized
  page plus a `next_cursor` (the same shape as today's first response, minus the
  500-object truncation).

**Bounds & configuration**

- **R5** The operator sets a maximum page size (`RECENT_CROSSMATCH_MAX_OBJECTS`
  is removed). A requested page size above the maximum is clamped down to it, not
  rejected — mirroring the endpoint's existing clamp-not-reject behavior.
- **R6** The operator sets a default page size, used when the caller omits one.
- **R7** There is no server-side total cap on the number of objects reachable
  across pages for a window. The existing maximum window-span bound is unchanged.

**Cursor semantics**

- **R8** The cursor encodes the keyset position (the sort key of the last object
  on the page) so the next page resumes immediately after it.
- **R9** A cursor is valid only for the exact query it was issued for (window
  start/end, `time_field`, `detail`); the cursor pins that context so query
  parameters cannot drift across a paged iteration. Presenting a cursor with
  conflicting query parameters is an error surfaced to the caller.
- **R10** Ordering is unchanged: newest-first by the selected `time_field`, with
  `diaObjectId` as the tiebreaker (a unique, total order).

**Stability**

- **R11** A full walk is a consistent descending snapshot as of iteration start
  for the two cases that matter for "pull the whole set": a **closed window**
  (e.g. last night, observing done) — the whole frozen set — and any window walked
  by **`ingest_time`** (the default), whose values are monotonic insertion times,
  so a concurrently inserted alert always sorts *above* the cursor and is never
  injected mid-walk. The one carve-out is an **open/rolling window walked by
  `event_time`**: `event_time` is immutable observation time, not insertion time,
  so an alert ingested mid-walk can carry an `event_time` *below* the current
  cursor yet inside the window. That walk is therefore read-committed, not a frozen
  snapshot — such a late arrival may appear (and, at an exact `event_time = t0`
  tie below the cursor, be skipped). It remains duplicate-free. This carve-out is
  documented in R14; the recommended pattern for exact completeness is a closed
  window (AE6).

**Response shape**

- **R12** `count` reports the number of objects in the current page, not a
  whole-set total (no cheap total exists under keyset paging).
- **R13** The page contract applies uniformly across all detail levels
  (`ids`/`position`/`matches`/`full`): page size counts objects, and each object
  still carries its nested matches.

**Documentation & example**

- **R14** `docs/api/recent-crossmatch-api.md` is updated to document the
  pagination contract — page size (default and maximum), `next_cursor`, cursor
  validity (R9), the stability guarantee including the open-window `event_time`
  read-committed carve-out (R11), and the per-page meaning of `count` — and to
  remove the retired total cap.
- **R15** `notebooks/recent_crossmatch_demo.ipynb` is updated to demonstrate
  paging: a loop that follows `next_cursor` to pull an entire window (e.g. last
  night's full set) into a pandas DataFrame.

### Acceptance Examples

- **AE1 (first page):** GET with no paging params over a window with more than
  the default page size of objects -> 200; `objects` holds exactly the default
  page size; `next_cursor` is present.
- **AE2 (follow to exhaustion):** repeatedly GET with the returned `next_cursor`
  -> the union of pages equals the window's full distinct diaObjectId set, each
  id appearing once; the final page returns `next_cursor` null.
- **AE3 (clamp):** a requested page size above the operator maximum -> served at
  the maximum page size, not rejected (400 is not returned for this).
- **AE4 (empty window):** a window with no matched objects -> 200, empty
  `objects`, `next_cursor` null.
- **AE5 (cursor/query mismatch):** a `next_cursor` presented with a different
  `time_field`, `detail`, or window than it was issued for -> rejected with 400.
- **AE6 (closed-window completeness):** paging last night's window to exhaustion
  yields the same distinct object count as a direct database count over that
  window — validating that "pull the entire set" actually returns everything.

### Scope Boundaries

Out of scope: rate limiting; authentication changes; offset / random-access
paging; a whole-set total count; changes to the crossmatch or ingest paths; and
any change to the matches-only semantics or the detail-level field sets
themselves (only how results are bounded and paged changes).

---

## Planning Contract

### Key Technical Decisions

- **KTD1 — Keyset predicate over the existing sort order.** The service already
  orders by `(time_field DESC, lsst_diaObject_diaObjectId ASC)` (see
  `crossmatch/api/service.py:119`). A cursor names the last row of the prior
  page as `(t0, id0)`; the next page is every row strictly after it in that
  order: `time_field < t0 OR (time_field = t0 AND diaObjectId > id0)`,
  ANDed with the window filter and the `Exists` matches-only semi-join. The
  query fetches `page_size + 1` rows; if the extra row comes back there is a
  further page (drop it and emit a `next_cursor` from the last kept row),
  otherwise `next_cursor` is null. The object projection must add the selected
  `time_field` column (today's query selects only id/ra/dec) so the last kept row
  carries its own `t0` for the cursor. Advances R1–R3, R10.
- **KTD2 — Opaque, unsigned base64url cursor.** The cursor is
  `base64url(compact JSON)` carrying the keyset position `(t0, id0)` plus the
  pinned query context (`start`, `end`, `time_field`, `detail`). It is
  **unsigned**: it encodes only public query parameters and a public keyset
  position, so a tampered cursor yields at most a different *valid* public query
  the client could have issued directly — there is no trust boundary to protect,
  and the endpoint is already unauthenticated. Clients treat it as opaque.
  The unsigned rationale holds *only because* decoded fields are re-validated
  exactly like directly-supplied params before any use (see KTD3): they are never
  fed raw into the ORM.
  Timestamps round-trip at full microsecond precision so the `=` arm of the
  keyset predicate holds exactly. A malformed/undecodable cursor -> `InvalidQuery`
  (400). Resolves the brainstorm's deferred "cursor encoding" question; advances
  R8.
- **KTD3 — Cursor pins the query; conflict rejects.** The cursor is authoritative
  for `{start, end, time_field, detail}`. `page_size` is independent (presentation,
  not result-set identity) and may be supplied alongside a cursor and vary per
  page. If the caller supplies `start`/`end`/`time_field`/`detail` that conflict
  with the cursor's pinned values -> 400; matching or omitted values are accepted;
  the service derives the pinned context from the cursor. The derived
  `time_field`/`detail` and `start`/`end` are then run through the *same* existing
  allowlist and `RECENT_CROSSMATCH_MAX_WINDOW_HOURS` span validation as
  directly-supplied params — a decoded `time_field` outside the allowlist (which
  would otherwise be interpolated into `Q(**{f"{tf}__lt": t0})` and `order_by`) or
  an over-span window raises `InvalidQuery` (400) *before* the keyset predicate is
  built, never reaching the ORM. Resolves the deferred "reject vs. pin" question in
  favor of reject-on-conflict; advances R9.
- **KTD4 — Page-size configuration replaces the object cap.**
  `RECENT_CROSSMATCH_MAX_OBJECTS` is removed. Add
  `RECENT_CROSSMATCH_DEFAULT_PAGE_SIZE` (default 1000) and
  `RECENT_CROSSMATCH_MAX_PAGE_SIZE` (default 10000), both env-overridable and
  read live from settings (matching the existing convention at
  `crossmatch/api/service.py:88`). A requested page size above the max clamps
  down; a non-integer or `<= 0` page size -> 400. No total cap;
  `RECENT_CROSSMATCH_MAX_WINDOW_HOURS` is unchanged. Note: `MAX_PAGE_SIZE` (10000)
  becomes the per-request work ceiling that the retired 500-object cap used to
  provide, and `full` detail is the heaviest per-object cost (a second DISTINCT ON
  payload build); this is an accepted interim exposure on the public-on-DEV
  posture, to revisit with the deferred rate-limiting work before any broader
  exposure. Advances R5–R7.
- **KTD5 — Envelope gains `page_size` and `next_cursor` (top-level).** The
  `_envelope` helper adds `page_size` (the effective size used) and `next_cursor`
  (null when exhausted); `count` stays per-page. `next_cursor` is a top-level
  field, not a nested `pagination` object — matching the flat envelope style.
  Resolves the deferred envelope-shape question; advances R12.
- **KTD6 — Stability is a property of descending keyset iteration.** Because each
  page resumes strictly after the last-seen `(t, id)`, the walk is always
  **duplicate-free** — a row is never revisited. The *snapshot* guarantee (no new
  rows injected mid-walk) holds when concurrently inserted rows sort *above* the
  cursor, which is true for a closed window (fully frozen) and for `ingest_time`
  (monotonic insertion time). It does **not** hold for an open/rolling
  `event_time` walk: `event_time` is immutable observation time
  (`crossmatch/core/models.py`), so a mid-walk insert can carry an `event_time`
  below the cursor and be injected (or tie-skipped) — that mode is read-committed,
  per the R11 carve-out. No snapshot/transaction is added; the closed-window path
  (AE6) is the exact-completeness contract. Inherent to KTD1; advances R3, R11.

### High-Level Technical Design

The cursor round-trip and the page loop:

```mermaid
sequenceDiagram
    participant C as Client
    participant V as view (api/views.py)
    participant S as service.recent_crossmatches
    participant P as pagination codec
    C->>V: GET ?detail=ids  (no cursor)
    V->>S: page_size=default, cursor=None
    S->>S: window filter + Exists, ORDER BY -tf, id, LIMIT page_size+1
    S->>P: encode_cursor(last_row, pinned ctx)
    S-->>V: {..., page_size, count, next_cursor, objects}
    V-->>C: 200 JSON
    C->>V: GET ?cursor=<next_cursor>
    V->>S: page_size, cursor (opaque, passed through unchanged)
    S->>P: decode_cursor -> keyset + pinned ctx
    S->>S: re-validate decoded time_field/detail/window; reject if explicit params conflict (400)
    S->>S: keyset predicate resumes after (t0,id0)
    S-->>C: next page (next_cursor=null when exhausted)
```

Keyset predicate (directional guidance, not final code):

```
# order is (time_field DESC, diaObjectId ASC); cursor = (t0, id0)
after_cursor = Q(**{f"{tf}__lt": t0}) | Q(**{tf: t0, "lsst_diaObject_diaObjectId__gt": id0})
# project tf too (as `t0`) — it is the last row's keyset timestamp the cursor encodes
rows = (Alert.objects.filter(**window).filter(Exists(has_match), after_cursor)
        .order_by(f"-{tf}", "lsst_diaObject_diaObjectId")
        .values("lsst_diaObject_diaObjectId", "ra_deg", "dec_deg", tf)[: page_size + 1])
has_next = len(rows) > page_size
page = rows[:page_size]
# encode_cursor reads page[-1][tf] (t0) and page[-1]["lsst_diaObject_diaObjectId"] (id0)
next_cursor = encode_cursor(page[-1], pinned) if has_next else None
```

### Assumptions

- `(time_field, lsst_diaObject_diaObjectId)` is a unique total order —
  `lsst_diaObject_diaObjectId` is `unique=True` on `Alert`
  (`crossmatch/core/models.py:27`), so the tiebreaker guarantees a deterministic,
  gap-free keyset.
- The `ingest_time` (default) and `event_time` windows are index-backed
  (`core_alert_ingest_time_idx`, `core_alert_event_time_idx`); the keyset
  predicate stays sargable against those btree indexes.
- Cursor timestamps serialize/deserialize losslessly at microsecond precision
  (the DB stores `timestamptz` at microsecond resolution).

### Sequencing

U1 (config) and U2 (cursor codec) are independent and land first. U3 (service)
depends on both. U4 (view) depends on U3. U5 (docs) and U6 (notebook) depend on
the U3/U4 contract being settled and can land together at the end.

---

## Implementation Units

### U1. Page-size configuration

- **Goal:** Replace the total-object cap setting with default/maximum page-size
  settings.
- **Requirements:** R5, R6, R7.
- **Dependencies:** none.
- **Files:**
  - `crossmatch/project/settings.py` (modify) — remove
    `RECENT_CROSSMATCH_MAX_OBJECTS`; add `RECENT_CROSSMATCH_DEFAULT_PAGE_SIZE`
    (`os.environ.get(..., '1000')`) and `RECENT_CROSSMATCH_MAX_PAGE_SIZE`
    (`os.environ.get(..., '10000')`), mirroring the existing
    `RECENT_CROSSMATCH_*` block at `crossmatch/project/settings.py:378`.
- **Approach:** Pure config. Keep `RECENT_CROSSMATCH_MAX_WINDOW_HOURS` untouched.
  The comment should note the page-size max bounds per-request work while total
  iteration is intentionally unbounded (KD3).
- **Patterns to follow:** the current `RECENT_CROSSMATCH_MAX_OBJECTS` /
  `RECENT_CROSSMATCH_MAX_WINDOW_HOURS` definitions.
- **Test scenarios:** `Test expectation: none -- pure config; behavior is
  exercised through U3/U4 tests (including an `@override_settings` page-size
  case).`
- **Verification:** `python manage.py check` passes; the two new settings resolve
  from env with the documented defaults.

### U2. Cursor codec

- **Goal:** An opaque, self-describing cursor that round-trips the keyset
  position and the pinned query context.
- **Requirements:** R8, R9.
- **Dependencies:** none.
- **Files:**
  - `crossmatch/api/pagination.py` (create) — `encode_cursor(...) -> str` and
    `decode_cursor(str) -> Cursor` (a small dataclass holding
    `time_field_value`, `dia_object_id`, `start`, `end`, `time_field`, `detail`);
    plus a helper that raises `InvalidQuery` when explicit request params conflict
    with the cursor's pinned context (KTD3).
  - `crossmatch/tests/test_pagination.py` (create).
- **Approach:** `base64url(compact JSON)` (KTD2), unsigned. Encode timestamps as
  full-precision ISO-8601. `decode_cursor` raises `InvalidQuery` on any
  malformed/undecodable input (bad base64, bad JSON, missing keys, unparseable
  values). `InvalidQuery` must be **hoisted to a shared module** (e.g.
  `crossmatch/api/errors.py`, re-exported from `service.py` for existing importers)
  so both `service.py` and `pagination.py` import it from there: U3 makes
  `service.py` import the codec from `pagination.py`, so a top-level
  `from api.service import InvalidQuery` in `pagination.py` would be a circular
  import. A function-local import is the fallback only if hoisting is undesirable.
- **Execution note:** Implement test-first — the encode/decode round-trip and the
  conflict rule are precise contracts.
- **Test scenarios:**
  - Round-trip: `decode_cursor(encode_cursor(x)) == x` for representative keyset
    + pinned-context values, including microsecond-precision timestamps.
  - `Covers AE5.` Conflict helper: a cursor whose pinned `time_field`/`detail`/
    window differs from the explicitly supplied param raises `InvalidQuery`;
    matching or omitted params do not.
  - Malformed cursor (non-base64, truncated, valid base64 of non-JSON, JSON
    missing a required key) each raises `InvalidQuery`.
  - The cursor string is URL-safe (no `+`/`/`/`=` padding issues as a query
    param).
- **Verification:** `pytest crossmatch/tests/test_pagination.py` green; a decoded
  cursor reproduces the exact keyset and pinned context it was built from.

### U3. Keyset paging in the service

- **Goal:** `recent_crossmatches` returns one keyset page plus a `next_cursor`,
  with no total cap.
- **Requirements:** R1, R2, R3, R4, R7, R10, R11, R12, R13.
- **Dependencies:** U1, U2.
- **Files:**
  - `crossmatch/api/service.py` (modify) — replace the `limit`/`cap` parameters
    with `page_size` and `cursor`; apply the keyset predicate (KTD1) when a cursor
    is present; clamp `page_size` to `RECENT_CROSSMATCH_MAX_PAGE_SIZE` and default
    it from `RECENT_CROSSMATCH_DEFAULT_PAGE_SIZE`; add the selected `time_field`
    column to the object `.values(...)` projection so the last kept row carries its
    own `t0`; fetch `page_size + 1` to detect a further page; derive `next_cursor`
    from the last kept row; extend `_envelope` with `page_size` and `next_cursor`.
  - `crossmatch/tests/test_recent_crossmatch_service.py` (modify) — replace the
    `limit`/`MAX_OBJECTS` clamp tests with page-size + cursor coverage.
- **Approach:** The window filter and the `Exists` matches-only semi-join are
  unchanged; the keyset `Q` is ANDed in. When a `cursor` is passed, the service
  derives `start`/`end`/`time_field`/`detail` from it (via U2), applies the
  conflict check against any explicit params, and routes the derived
  `time_field`/`detail`/window through the *same* existing allowlist and
  `RECENT_CROSSMATCH_MAX_WINDOW_HOURS` validation as directly-supplied params
  (KTD3) before building the keyset `Q` — a decoded value that fails validation
  raises `InvalidQuery` and never reaches the ORM. `page_size + 1` fetch drives
  `next_cursor`. `count` stays `len(page)`. Preserve the existing per-row
  defensive `_load_matches` and DISTINCT ON dedup untouched.
- **Patterns to follow:** the existing object query and `_envelope` in
  `crossmatch/api/service.py`; the live-settings read at
  `crossmatch/api/service.py:88`.
- **Execution note:** Implement test-first — AE1–AE4 and AE6 specify the paging
  contract precisely.
- **Test scenarios:**
  - `Covers AE1.` No cursor, window with > default page size of matched objects
    -> `len(objects) == default page size`, `next_cursor` present, `page_size`
    echoed.
  - `Covers AE2.` Seed N objects across the window; follow `next_cursor` to
    exhaustion with a small page size -> the union of pages is exactly the N
    distinct ids, each once, in newest-first order; the final page has
    `next_cursor is None`. Include a tie case: several objects sharing one
    `time_field` value split across a page boundary are neither dropped nor
    duplicated (exercises the `diaObjectId` tiebreaker arm of the predicate).
  - `Covers AE3.` `page_size` above `RECENT_CROSSMATCH_MAX_PAGE_SIZE` -> served at
    the max, not rejected (use `@override_settings` to keep the fixture small).
  - `Covers AE4.` Empty window -> `objects == []`, `next_cursor is None`, 0 count.
  - Detail levels: paging works for `ids`/`position`/`matches`/`full`; a page
    carries each object's nested matches (R13); the `full` per-row defensive skip
    still holds across a page boundary.
  - `page_size` non-integer or `<= 0` raises `InvalidQuery`.
  - A cursor built for one query resumes correctly for that same query
    (`start`/`end`/`time_field`/`detail` derived from the cursor).
  - `count` equals `len(objects)` on a partial and a full page (never a whole-set
    total).
  - Decoded-cursor re-validation: a cursor whose *pinned* `time_field` is outside
    the allowlist, or whose pinned window exceeds
    `RECENT_CROSSMATCH_MAX_WINDOW_HOURS`, raises `InvalidQuery` (400) before any
    query runs — the unsigned cursor cannot smuggle an invalid `time_field` into
    the ORM (`@override_settings` on the window bound to keep the fixture small).
  - `event_time` open-window carve-out (R11): with `time_field='event_time'` and
    an open window, insert a row mid-walk whose `event_time` falls *below* the
    current cursor but inside the window; assert the walk stays duplicate-free and
    characterize whether that late arrival appears (documents the read-committed
    behavior rather than asserting a frozen snapshot).
- **Verification:** `pytest` service tests green; walking a seeded window to
  exhaustion reconstructs the full distinct set.

### U4. View and route

- **Goal:** The HTTP layer accepts `page_size` and `cursor`, drops `limit`, and
  maps cursor/param conflicts to 400.
- **Requirements:** R1, R2, R4, R9.
- **Dependencies:** U3.
- **Files:**
  - `crossmatch/api/views.py` (modify) — parse `page_size` (int) and `cursor`
    (str); remove `limit`/`_parse_limit`; pass through to the service; keep the
    `InvalidQuery -> 400` and non-GET -> 405 behavior; refresh the docstring.
  - `crossmatch/tests/test_recent_crossmatch_view.py` (modify) — replace the
    `limit` tests with `page_size`/`cursor` coverage.
- **Approach:** Thin adapter, unchanged in shape. `page_size` parses like the old
  `limit` (non-integer -> 400 via `InvalidQuery`); `cursor` is passed as an opaque
  string. Conflict detection and clamping live in the service/codec (U2/U3), so
  the view stays declarative.
- **Patterns to follow:** the existing `recent_crossmatches_view` param loop.
- **Test scenarios:**
  - `Covers AE1.` No params -> 200, default page, `next_cursor` present,
    `page_size` in the body.
  - `Covers AE2.` Follow `next_cursor` across two GETs through the real URLconf ->
    disjoint pages that together cover the seeded set.
  - `Covers AE5.` A `cursor` plus a conflicting `time_field`/`detail`/window ->
    400 JSON error.
  - `Covers AE3.` `page_size` above the max -> 200 at the clamped size.
  - Non-integer `page_size` -> 400; a malformed `cursor` -> 400.
  - `limit` is no longer honored (a stray `?limit=1` does not truncate the page).
  - Endpoint still serves unauthenticated (no redirect/401); non-GET -> 405.
- **Verification:** `pytest` view tests green; a local `gunicorn`/`runserver`
  request pages through a window to exhaustion.

### U5. API documentation

- **Goal:** Document the pagination contract and remove the retired cap.
- **Requirements:** R14.
- **Dependencies:** U3, U4.
- **Files:**
  - `docs/api/recent-crossmatch-api.md` (modify) — document `page_size` (default
    and max), `cursor`/`next_cursor`, the opaque-cursor and pin-the-query rules
    (KTD2/KTD3), the descending-keyset stability guarantee and its open-window
    `event_time` read-committed carve-out (R11), and the
    per-page meaning of `count`; remove the `RECENT_CROSSMATCH_MAX_OBJECTS` /
    total-cap text and the old `limit` param.
- **Approach:** Mirror the field sets and examples to the implemented shape;
  include a short "walk the whole set" example that follows `next_cursor`.
- **Test scenarios:** `Test expectation: none -- documentation; correctness is
  the doc matching the U3/U4 response shape.`
- **Verification:** the doc's request/response examples match the implemented
  envelope and error contract.

### U6. Demo notebook

- **Goal:** Show pulling an entire window via paging.
- **Requirements:** R15.
- **Dependencies:** U3, U4.
- **Files:**
  - `notebooks/recent_crossmatch_demo.ipynb` (modify) — add a cell that loops on
    `next_cursor` until null, accumulating objects into a single pandas DataFrame
    (e.g. last night's full set); keep an existing single-page example for
    contrast.
- **Approach:** A small `while next_cursor` loop over the existing `httpx` client;
  demonstrate at least the `ids` and `matches` levels and report the total pulled
  vs. a single page.
- **Test scenarios:** `Test expectation: none -- the notebook running top-to-
  bottom against a live endpoint is the acceptance signal.`
- **Verification:** the notebook runs cleanly and the paged pull count matches a
  direct DB count for the window (AE6 spirit).

---

## Verification Contract

| Gate | Command | Applies to |
|---|---|---|
| App unit tests | `pytest` in-container (per `docs/developer.md`: `docker compose --env-file docker/.env -f docker/docker-compose.yaml run --rm --no-deps celery-worker sh -c 'pip install -q -r requirements.dev.txt && python -m pytest'`) | U1, U2, U3, U4 |
| Django check | `python manage.py check` clean | U1 |
| Serving smoke | `gunicorn project.wsgi:application` boots; a request pages a window to exhaustion via `next_cursor` and the union of pages equals a direct DB count | U3, U4 |
| Notebook | `notebooks/recent_crossmatch_demo.ipynb` runs top-to-bottom against a live endpoint | U6 |

No new migration is introduced; the existing `ingest_time`/`event_time` indexes
back the keyset predicate.

---

## Definition of Done

- The endpoint returns one operator-bounded page per request with a top-level
  `next_cursor`, and following the cursor to exhaustion returns a window's whole
  distinct diaObjectId-with-match set exactly once (R1–R4, R10–R13, AE1–AE6).
- `RECENT_CROSSMATCH_MAX_OBJECTS` is gone; page size is bounded by
  `RECENT_CROSSMATCH_MAX_PAGE_SIZE` (clamp-not-reject) and defaults to
  `RECENT_CROSSMATCH_DEFAULT_PAGE_SIZE`; there is no total cap (R5–R7).
- A cursor is opaque, pins its query context, and a conflicting request param is
  rejected with 400 (R8, R9, AE5).
- API documentation and the demo notebook match the implemented paging shape
  (R14, R15).
- App unit tests pass in-container; `manage.py check` is clean.

---

## Sources / Research

- `docs/plans/2026-07-13-001-feat-recent-crossmatch-api-plan.md` — the shipped
  endpoint this evolves; establishes the envelope, detail levels, matches-only
  semantics, and the `RECENT_CROSSMATCH_*` ceilings being changed.
- `crossmatch/api/service.py` — the object query, `(‑time_field, diaObjectId)`
  ordering (the keyset basis), live-settings read, `_load_matches` DISTINCT ON,
  and `_envelope`.
- `crossmatch/api/views.py` — the thin GET adapter and current `limit` parsing.
- `crossmatch/project/settings.py:378` — the `RECENT_CROSSMATCH_*` settings block.
- `crossmatch/core/models.py:27` — `lsst_diaObject_diaObjectId` uniqueness (the
  keyset totality guarantee) and the `ingest_time`/`event_time` indexes.
