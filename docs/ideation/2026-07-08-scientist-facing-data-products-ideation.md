---
date: 2026-07-08
topic: scientist-facing-data-products
focus: scientist-facing data products (object payload lookup, ranked transient candidates, sky-region queries) exposed three ways — web app, REST API, and agent/MCP interface
mode: repo-grounded
---

# Ideation: Scientist-facing data products for the SCiMMA crossmatch service

This ideation covers **scientist-facing** read/query surfaces for domain astronomers and astrophysicists — the audience the 2026-04-28 operator-dashboard ideation explicitly deferred ("Scientist-facing surfaces ... belong in a separate ideation with their own audience analysis"). This is that ideation. Operator/monitoring surfaces are out of scope here.

The seed question: the maintainer proposed three data products — (1) deliver the Hopskotch payload for a given `diaObjectId`, (2) deliver the N `diaObjectId`s with the highest probability of being a transient from the last M hours, (3) deliver the N `diaObjectId`s in a sky patch from the last M hours — each exposed via a web app (`crossmatch-dev.scimma.org`), a REST API, and an agent/MCP interface. Are they good ideas, and what else? Short answer: **all three are good and worth building; each has a concrete data-layer prerequisite that does not exist yet, and the highest-leverage move is to build the shared read model those prerequisites imply before building any single query.**

## Grounding context

### Codebase context (ground truth, from a code scan — not the design doc)

- **No HTTP surface exists yet.** No `urls.py`, `views`, DRF, django-ninja, ASGI/channels, `ROOT_URLCONF`, or `WSGI/ASGI_APPLICATION` anywhere under `crossmatch/` (`crossmatch/project/settings.py:142-154`). Entrypoints are all non-HTTP: broker consumers, Celery worker/beat, Flower. **Every scientist-facing surface is greenfield** — there is no request/response layer to extend.
- **The published payload IS stored** (not recomputed): built once at crossmatch time and persisted verbatim on `Notification.payload` (`crossmatch/tasks/crossmatch.py:134-167`), read unchanged at publish (`crossmatch/notifier/impl_hopskotch.py:33`). So "payload for a `diaObjectId`" is a **lookup**. Caveat: **one `Notification` per match** (per catalog), so a `diaObjectId` returns multiple payload rows; zero-match alerts have none.
- **The "probability of being a transient" (LSST `reliability`) is present in the raw `payload` but NOT persisted as a first-class column.** All three `normalize_*` store the raw broker message verbatim as `Alert.payload` (`raw_alert` / `alert.dict`, `crossmatch/brokers/normalize.py:16-74`), so `reliability` rides through with no per-broker payload code — but only buried, untyped, and unindexed inside JSONB. Live DEV verification (see the dated note below) shows it present on **100% of ANTARES-native payloads** (flat `payload.lsst_diaSource_reliability`) and **100% of Pitt-Google payloads** (nested `payload.diaSource.reliability`), and **not yet observed for Lasair** (its filter carries only `diaObjectId/ra/decl/firstDiaSourceMjdTai`; the maintainer edited the upstream filter to add reliability starting 2026-07-08 but post-edit alerts had not surfaced it at inspection time). Ranking by transient probability requires extracting it to a first-class indexed column, with a per-broker path map and an object-level aggregation rule (reliability is per-diaSource; one object can be delivered by multiple brokers with differing values).
- **No spatial support at all.** `ra_deg`/`dec_deg` are unindexed `FloatField`s (`crossmatch/core/models.py:31-33`); no PostGIS/GeoDjango, no q3c, no HEALPix column, no cone-search helper, and RA wraparound at 0/360 is unhandled. A sky-patch query today is a full-table scan.
- **No time indexing.** `event_time`/`ingest_time` are unindexed (`models.py:35-37`). "Last M hours" is an unindexed scan today.
- **Cardinality:** one `Alert` per `diaObjectId` (`unique=True`); multiple `CatalogMatch`/`Notification` per `diaObjectId`; zero-match alerts are retained (queryable via `catalogmatch__isnull=True`).

### Live DEV verification (2026-07-08, against the deployed `django-db`, 1,049,463 alerts)

Queried the DEV Postgres directly to settle the seed-idea-#2 (ranked-transient) reliability question:

- **`reliability` cross-broker availability (classified by payload shape, not by `alert_deliveries` join):** ANTARES-native `payload.lsst_diaSource_reliability` present on 100% of sampled native payloads (value range 0.601–0.998, avg 0.715 — a 0–1 RB score floored at 0.6 by `MIN_DIASOURCE_RELIABILITY`); Pitt-Google `payload.diaSource.reliability` present on 100% (range 0.60–1.0); Lasair not yet carrying it in ingested alerts as of the newest window (ingest through 2026-07-08 06:43 UTC). **Seed idea #2 is salvageable** — 2 of 3 brokers already carry reliability universally, Lasair is en route via the upstream filter edit, and `payload = raw message` means it persists automatically once alerts flow.
- **Correction to a prior assumption:** an earlier read that ANTARES carried reliability on only ~2.7% of alerts was a join artifact — `core_alert` holds one payload per `diaObjectId` (`uuid` PK, `diaObjectId` unique), but an object is often delivered by multiple brokers, so joining to `alert_deliveries` returned whichever broker's payload was stored. Shape-based classification shows ANTARES-native payloads carry reliability 100%.
- **Performance evidence for the read model (idea #1):** full-table JSONB predicate scans over the 1M-row `core_alert` **time out (>2 min)** repeatedly, even for simple `payload ? 'key'` presence checks. "Top N by reliability in the last M hours" and sky-region queries cannot run off JSONB or unindexed `event_time`/`ra_deg`/`dec_deg` — this is direct, measured evidence that the indexed read model is a hard prerequisite, not an optimization.

### External context (prior art — every claim sourced in the research briefing)

- **The mature-broker query surface is remarkably uniform** across ANTARES, ALeRCE, Lasair, Fink, Pitt-Google, Babamul: object lookup by ID, cone/region search, SQL/ADQL over an object DB, classification + real-bogus filtering, crossmatch/context labeling, watchlists/watchmaps, and light-curve/forced-photometry retrieval — delivered through **pip-installable Python clients, token REST APIs, and filter-as-Kafka-topic streams**. Fink's REST API (`/objects`, `/conesearch`, `/latests` + date window, `/resolver`) is a concrete template.
- **The two closest functional analogues to *this* service are Lasair's Sherlock and ALeRCE's DELIGHT** — contextual catalog crossmatch/labeling and host association. Our positional HATS crossmatch is the same *kind* of thing: a context-enrichment layer, not another general-purpose broker. That is the differentiation.
- **VO protocols lower adoption to zero client code.** Simple Cone Search (SCS), TAP/ADQL, and MOC are IVOA standards that TOPCAT, Aladin, astroquery, and pyvo already speak; the Rubin Science Platform itself exposes TAP/ADQL. **MOC is HEALPix-based and therefore architecturally adjacent to our HATS stack** — the idiomatic way to publish "which sky regions do we cover" and to test region overlap (Lasair already uses MOC FITS for watchmaps).
- **Agent/MCP interfaces in astronomy are prototype-grade (mid-2026).** `astro_mcp` wraps astroquery; NL→SQL over broker DBs (ALeRCE text-to-SQL) drops to **44–59% accuracy on medium/hard queries**; autonomous agents over a live alert stream have **no production precedent** (Rubin's ~10M alerts/night makes per-alert LLM calls unrealistic). Realistic today: an **MCP server exposing structured tools** (not NL→SQL) and literature RAG.
- **Scientist needs, ranked:** rapid real-transient identification (the ~10M/night firehose), host/counterpart association, **rejecting known variables/SSOs**, sky-region monitoring/watchlists, reproducible programmatic access.

### Past learnings

`docs/solutions/` is populated. Directly relevant: the payload-coercion and per-catalog `payload_columns` patterns (`docs/solutions/design-patterns/coerce-numpy-pandas-scalars-to-json.md`, `docs/solutions/conventions/catalog-specific-payload-columns.md`) define the exact shape any read API would return. The 2026-04-28 operator-dashboard ideation parked several science-side ideas as out-of-scope ("Metabase read-replica", "Saved Filters → Hopskotch republish topics", "TOM Toolkit plugin", "Jupyter library", "HEALPix sky map") — now in scope here and folded into the survivors below.

### Topic axes

1. **Data products / query patterns** — the scientific questions the service answers.
2. **Delivery channels + shared contract** — web app, REST API, agent/MCP, and the query core beneath them.
3. **Science value-add / enrichment** — what makes matches scientifically useful (context, contaminant rejection, coverage).
4. **Push / subscription vs one-shot pull** — standing queries, watchlists, notifications.
5. **Workflow integration** — TOM/SkyPortal, VO protocols, Python client, reproducibility.

## Ranked ideas

### 1. Build the scientist read model (the foundational substrate)
**Description:** Before any query surface, build the read model all three seed ideas sit on: (a) extract `reliability` to a first-class, indexed column on `Alert` at normalization time, using a **per-broker path map** — ANTARES `payload.lsst_diaSource_reliability` (flat), Pitt-Google `payload.diaSource.reliability` (nested), Lasair `payload.latestR` (flat; upstream filter edited 2026-07-08 to emit it) — with a null convention for alerts that lack it and an object-level aggregation rule (reliability is per-diaSource; one object may be delivered by multiple brokers); (b) add a spatial index for region queries — either the `q3c` Postgres extension or a HEALPix `ipix` column (the latter is adjacent to our existing HATS/HEALPix stack), and handle RA wraparound; (c) index `event_time`; (d) optionally materialize an object-level record so a `diaObjectId` is one row rather than N match rows. Consider placing this read model on a read replica or a denormalized science store so scientist queries never contend with the ingest write path.
**Warrant:** `direct:` verified against the live DEV `django-db` (1M alerts) — `reliability` lives only untyped/unindexed inside `Alert.payload` (present 100% for ANTARES and Pitt-Google native payloads, Lasair pending; `brokers/normalize.py:16-74`, `settings.py:260-275`), `ra_deg/dec_deg` and `event_time` are unindexed (`core/models.py:31-37`), payloads are per-match (`tasks/crossmatch.py:134-167`), and **full-table JSONB/unindexed scans time out (>2 min)** at current volume. `external:` every mature broker exposes exactly these query axes, implying the same backing indexes.
**Rationale:** All three seed ideas and most survivors below decompose into "query this read model." Building it once is the compounding move; building any single endpoint first re-derives a slice of it and strands the rest. The live-DB measurement confirms this is a correctness/feasibility prerequisite (queries time out today), not just a performance nicety — seed idea #2 is not buildable as stated until it lands.
**Downsides:** Schema + backfill migration; the per-broker `reliability` map means "highest probability" is only honest for brokers that carry the value (2 of 3 today; Lasair pending confirmation) — this must be surfaced in the API, not hidden. q3c vs HEALPix-column is a real decision (q3c is turnkey Postgres; HEALPix reuses our stack and enables MOC overlap).
**Confidence:** 90%
**Complexity:** Medium
**Status:** Unexplored

### 2. One query core, three thin adapters (REST + Python client, web, MCP)
**Description:** Because the HTTP surface is greenfield, design a single internal query/service layer once and expose it three ways rather than building three parallel stacks: a token-authenticated **REST API** (JSON + CSV/VOTable output), a **pip-installable Python client** thinly wrapping it (the universal broker-access pattern, reproducible in pipelines), a **web app** for interactive use, and an **MCP server exposing structured tools** — `get_object(diaObjectId)`, `cone_search(ra, dec, radius)`, `rank_transients(hours, n)`, `region_objects(moc|patch, hours)` — deliberately **not** an NL→SQL layer.
**Warrant:** `external:` every broker ships a REST API + pip client (`antares-client`, `alerce`, `lasair`, `fink-client`); `astro_mcp` demonstrates the structured-tool MCP pattern; ALeRCE's NL→SQL benchmarks at 44–59% on hard queries, so structured tools are the reliable agent surface. `reasoned:` with no legacy HTTP surface to retrofit, a contract-first core makes the three-way exposure the maintainer asked for nearly free — the adapters are serialization, not re-implementation.
**Rationale:** This is the architecture answer to "expose it three ways." Three independent surfaces would triple the query logic and drift; one core keeps them consistent and makes the MCP interface a thin, honest wrapper over the same tools a human calls.
**Downsides:** Requires an up-front auth/rate-limit decision (Lasair's tiered token model is a precedent) and API-versioning discipline. MCP is prototype-grade in the ecosystem — novel here, but low adoption risk since it wraps the same structured tools.
**Confidence:** 85%
**Complexity:** Medium-High
**Status:** Unexplored

### 3. The three seed queries, sharpened (payload lookup · ranked transients · region search)
**Description:** The maintainer's three products, validated and made precise against the read model (#1): **(a) Object payload/dossier** — `get_object(diaObjectId)` aggregates the stored `Notification` payloads + `CatalogMatch` rows into one object-level record (clean lookup; decide per-object vs per-match shape). **(b) Ranked transient candidates** — top-N by persisted `reliability` within the last M hours (default 24), with the cross-broker availability caveat exposed as a field, not hidden. **(c) Sky-region search** — cone or patch (and, later, MOC region) within the last M hours, over the spatial + time indexes.
**Warrant:** `direct:` payloads are stored and keyed on the alert (`tasks/crossmatch.py:134-167`), so (a) is a lookup; (b) and (c) are blocked only by the missing `reliability`/spatial/time indexes (#1) — the code and live-DB inspection confirm the exact gaps. Live DEV verification shows (b) is genuinely feasible: reliability is present on 100% of ANTARES and Pitt-Google native payloads (0–1 score, floored at 0.6) with Lasair en route, so a ranked-transient list has real data to rank today.
**Rationale:** These are the concrete deliverables scientists will actually call, and they map one-to-one to the seed question. Sequenced after #1, each is a small, well-bounded endpoint rather than a research project.
**Downsides:** (a) must define object-vs-match aggregation (a `diaObjectId` has N matches); (b) is meaningful for the 2 of 3 brokers that carry `reliability` today (Lasair pending) and must expose per-broker availability as a field rather than silently ranking an incomplete set; (c) needs RA-wrap correctness (an easy source of silent wrong answers near 0/360).
**Confidence:** 90%
**Complexity:** Low-Medium (given #1)
**Status:** Unexplored

### 4. Lean into the crossmatch/context identity — "known source?" and per-object context
**Description:** Position the service as the **context/enrichment layer** (the Sherlock/DELIGHT role) rather than another general broker, and expose that as product: a "is this a known source / likely contaminant?" signal derived from the catalog matches (e.g., matches a Gaia star or a known variable within the radius), and a per-object "catalog context" view summarizing what each survey says at that position.
**Warrant:** `external:` the two closest analogues to a positional HATS crossmatch service are Lasair/Sherlock (contextual labeling) and ALeRCE/DELIGHT (host association); "rejecting known variables/SSOs" is a top-ranked scientist need. `direct:` we already compute and store per-catalog matches with separations (`CatalogMatch`, `core/models.py:81-114`) — the raw material for a contaminant flag is already on disk.
**Rationale:** This is the service's non-substitutable value. General alert lookup is commoditized across seven brokers; "here is the multi-survey catalog context for this detection, and whether it's a known thing" is what our crossmatch uniquely produces. It reframes the product from "a smaller broker" to "the context oracle other tools call."
**Downsides:** "Known variable" is a judgment layer on top of a positional match (a Gaia match ≠ variability); honest labeling requires care about what a match does and doesn't imply. Scope discipline needed so it doesn't drift toward full classification (which we don't do).
**Confidence:** 80%
**Complexity:** Medium
**Status:** Unexplored

### 5. VO-protocol front door — Simple Cone Search + TAP/ADQL + a MOC coverage map
**Description:** Expose the region/query surface through IVOA standards so scientists use existing tools with zero client code: **Simple Cone Search** and **TAP/ADQL** over the read model, and publish a **MOC coverage map** describing which sky (and per-catalog) regions the service actually covers — so a null result is interpretable (e.g., DES Y6 Gold is southern-only, so no match outside its footprint is expected, not a bug).
**Warrant:** `external:` SCS/TAP/ADQL/MOC are IVOA Recommendations spoken by TOPCAT, Aladin, astroquery, pyvo; the Rubin Science Platform exposes TAP/ADQL as the native idiom for data-rights users; `mocpy` provides region set-ops. `reasoned:` MOC is HEALPix-based and adjacent to our HATS stack, so coverage export is close to free; the DES southern-footprint "no overlap is normal" behavior is already a documented gotcha that a coverage map turns into a first-class answer.
**Rationale:** The cheapest adoption lever available: it converts "learn our API" into "paste our endpoint into the tool you already use." A coverage MOC also pre-empts the most common false-alarm support question ("why no matches here?").
**Downsides:** TAP/ADQL is a heavier implementation than a bespoke REST endpoint (an ADQL-to-SQL translation layer, or an existing library); may be Phase-2 relative to the plain REST API in #2. Cone-search VOTable formatting is fiddly.
**Confidence:** 70%
**Complexity:** Medium-High
**Status:** Unexplored

### 6. Saved filters → subscription topics, plus watchlists/watchmaps
**Description:** Let scientists define standing queries (sky region, reliability threshold, catalog) that republish matching results to a per-user Hopskotch topic (the filter-as-topic pattern), and let them upload **watchlists** (target RA/Dec lists → notify on match with separation) and **watchmaps** (MOC regions — e.g. a gravitational-wave skymap → notify on any match inside).
**Warrant:** `external:` Fink names each user filter as its own Kafka topic; Lasair provides watchlists (catalog cone-match) and watchmaps (MOC FITS, incl. GW skymaps); ANTARES persistent filters flag GW regions. `direct:` the notifier + Hopskotch publish path already exists end-to-end (`crossmatch/notifier/impl_hopskotch.py`), so republishing to a new topic reuses shipped infrastructure. (Parked as out-of-scope in the operator-dashboard ideation; now in scope.)
**Rationale:** Converts the service from one-shot pull to standing subscription — the mode multi-messenger/GW follow-up actually uses ("tell me when anything lights up inside this LIGO skymap"). Reuses the crossmatch and notifier we already run.
**Downsides:** Per-user topic lifecycle + auth + quota management is real operational surface; watchmap ingestion needs MOC handling (shared with #5). Belongs after the core read/query API.
**Confidence:** 70%
**Complexity:** Medium
**Status:** Unexplored

### 7. Link out, don't rebuild — a resolver to broker light curves and TNS
**Description:** The service is **positional-only** — it has no light curves or forced photometry. Rather than rebuild them, add a resolver that, for a given `diaObjectId`/position, links out to the object's light-curve pages at ANTARES/Lasair/Fink and to its **TNS** name/classification, and (optionally) ingests classifier labels the other brokers already publish.
**Warrant:** `external:` Fink's `/resolver` (SIMBAD/TNS/SSO) and the cross-broker pattern where brokers ingest each other's annotations; light-curve + forced-photometry retrieval is a top scientist need we structurally cannot serve. `direct:` the matching path is purely positional (per the design doc and `matching/`), so light curves are out of our data.
**Rationale:** Keeps scope honest and makes the service a good citizen in the ecosystem instead of a worse copy of a broker. A scientist who finds an interesting object in our context view can reach its light curve in one click without us storing a single flux point.
**Downsides:** Depends on external services' URL schemes and uptime; adds no data of our own (some will see it as thin). Best as a small enhancement on the object view (#3a/#4), not a standalone build.
**Confidence:** 65%
**Complexity:** Low
**Status:** Unexplored

## Cross-cutting compositions

Not separate ideas — coherent ways to phase the survivors into a build.

- **The substrate is the unlock — #1 first, always.** Every other survivor is "query the read model." Persisted `reliability` + spatial + time indexes are the prerequisite seed idea #2 and #3 silently assume. Ship #1 before any endpoint.
- **MVP = #1 + #2 + #3.** The read model, the one-core-three-adapters architecture, and the three seed queries are exactly what the maintainer asked for, and together they are the smallest thing that delivers the web app + REST API + MCP interface over real data.
- **Differentiation layer = #4 + #5 + #7.** Context/"known source" identity, VO front door + coverage MOC, and resolver link-outs are what make this *the crossmatch context service* rather than a smaller seventh broker — and #5/#6 share the MOC machinery.
- **Subscription layer = #6.** Once the read model and query core exist, standing filters + watchmaps reuse the notifier we already run; this is the GW/multi-messenger follow-up mode and a natural Phase 2.
- **Phasing.** Phase 0: #1 (read model). Phase 1: #2 + #3 (query core, three adapters, three seed queries — the asked-for MVP). Phase 2: #4 + #5 + #7 (differentiation) then #6 (subscriptions).

## Rejection summary

| # | Idea | Reason rejected |
|---|------|-----------------|
| 1 | Natural-language → SQL/ADQL query interface | Research-stage: 44–59% accuracy on medium/hard queries (ALeRCE text-to-SQL). Reframed as structured MCP tools, folded into #2. |
| 2 | Autonomous agent reasoning over the live alert stream | No production precedent; ~10M alerts/night makes per-alert LLM calls uneconomical. Operated brokers classify with CNNs/RFs, not LLMs. |
| 3 | Rebuild light curves / forced photometry | We are positional-only — not our data. Link out via the resolver (#7) instead of building a worse copy. |
| 4 | Host-galaxy association (DELIGHT/GHOST-style) | Genuinely valuable but a heavy ML build beyond positional crossmatch and current data; too expensive relative to near-term value. Revisit after #1–#4. |
| 5 | Image cutouts / difference-image stamps | We hold no image data; structurally impossible without a new pipeline. |
| 6 | Metabase / BI tool over a Postgres read-replica | Superseded by the query API (#2/#3) which serves scientists better than ad-hoc BI; the read-replica idea itself is folded into #1. |
| 7 | Deploy full SkyPortal/Fritz as our surface | That is a downstream follow-up marshal, not our context layer; integrate via a TOM/broker module instead of operating a marshal. |
| 8 | TNS auto-submission discovery bot | Discovery-claiming is a policy/authorship decision, not a data-product one; better as a `ce-brainstorm` topic than an ideation survivor. |
| 9 | Generic "science dashboard" | Too vague; dominated by the specific query surfaces (#3) and the context view (#4). |

_Axis coverage: all five axes carry at least one survivor (A1: #1, #3; A2: #2; A3: #4, #7; A4: #6; A5: #5, #7). No deliberate gaps._

_Process note: the fresh-context basis verification was performed by the two Phase-1 grounding agents (a codebase scout for the `direct:` bases and a prior-art researcher for the `external:` bases) rather than a separate Phase-3 verifier; every `direct:` basis cites a scanned `file:line` and every `external:` basis a sourced result._
