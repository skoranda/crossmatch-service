---
status: active
type: refactor
origin: docs/brainstorms/2026-06-12-refresh-service-design-doc-requirements.md
date: 2026-06-12
---

# refactor: refresh `scimma_crossmatch_service_design.md` against recent work

## Summary

Update the service architecture design doc so it agrees with the work landed since 2026-04-27: catalog-specific payload columns, the four-catalog roster, Pitt-Google in diagrams and enums, current module layout, the actual Hopskotch published-message shape, the as-built `alert_deliveries` model, the real Helm chart name, and a single §9.1 paragraph pointing at the k8s GitOps repo and plan. Five focused doc-edit units against one target file, sequenced so the §4.6 Hopskotch payload update lands on a canonical shape derived from the publishing code rather than a hedge.

---

## Problem Frame

`scimma_crossmatch_service_design.md` was last edited on 2026-04-27 (`5e77ca4 docs(broker-filter): standardize broker filter on reliability >= 0.6`). Six weeks of substantive work have landed since — catalog-specific payload columns (PR #44), the LSDB v0.9.0 upgrade (PR #42), and the k8s GitOps + image-publishing track (PRs #45–53) — plus four `docs/solutions/` docs that future readers will want to discover from the design doc's relevant sections.

The doc currently tells a reader several things that are factually wrong (the Hopskotch payload shape, the broker enum, the Helm chart name, the "TARGET LAYOUT" refactor comment, the `_get_catalog` code snippet from before the schema validation guard), enumerates two catalogs in several places when four are live, and is silent on the deployment story that landed in PRs #45–53. A fresh reader following the doc cold would build the wrong Hopskotch consumer schema and would not find the new `docs/solutions/` references when implementing in the area.

The refresh is doc-only: where the design doc and the code disagree (most visibly in §5.2.1b `alert_deliveries` fields), the doc gets trimmed to match the model rather than the model getting catching-up changes. No code is modified by this plan.

---

## Key Technical Decisions

**KTD1 — Doc reflects as-built; no code changes.** Fields the design doc currently documents that aren't in the code (`AlertDelivery.broker_alert_id`, `AlertDelivery.raw_payload`, `AlertDelivery.delivered_at`) get trimmed from the doc rather than added to the model. The deferred idempotency-and-replay intent (per-broker alert id, raw envelope, separate delivery timestamp) is preserved in OQ-Plan-2 below so the rationale survives this refresh. Catching up the model — including the stale `# 'antares' | 'lasair'` comment in `crossmatch/core/models.py:64` — is out of scope (see Scope Boundaries / Deferred Follow-Up Work). *(see origin: docs/brainstorms/2026-06-12-refresh-service-design-doc-requirements.md — Key Decisions)*

**KTD2 — K8s GitOps stays out beyond a single §9.1 paragraph.** The GitOps story lives in two repos (this one + `crossmatch-service-k8s-gitops` on GitLab) with its own implementation plan at `docs/plans/2026-06-02-001-feat-crossmatch-service-k8s-gitops-plan.md`. §9.1 in the design doc gets one paragraph (R12 + R13 co-located per Success Criterion 3) naming the gitops repo, the image-publish via `.github/workflows/build-image.yml` to the public GitLab Container Registry, the anonymous cluster pull, and the deploy env-var contract guardrail at `deploy-contract.yaml` (PR #45). No mechanics (registry choice rationale, sealed-secret arrangement, Helm overlay shape) are ported into this doc. *(see origin: Key Decisions)*

**KTD3 — Catalog enumerations generalize, asymmetries surface in one place.** "Gaia DR3 and DES Y6 Gold" enumerations in §2.1 C / §3 / §8.4 / §3.1 generalize to "all configured HATS catalogs" (the authoritative four-catalog list stays in §7.3). §11.1 is exempt — it is a historical first-milestone marker preserved per Scope Boundaries. The brainstorm-confirmed asymmetry callout in §7.3 absorbs the case-convention split, J2000 suffix, partial-footprint reality, per-catalog `payload_columns` divergence, and margin-cache availability differences so the generalization doesn't erase per-catalog detail a reader needs. *(see origin: Key Decisions; doc-review Apply Finding 7)*

**KTD4 — §4.6 Hopskotch payload shape is pinned inline, derived from the publishing code.** The §4.6 example reflects the dict actually constructed at `crossmatch/tasks/crossmatch.py:120-132` and published verbatim by `crossmatch/notifier/impl_hopskotch.py:32` via `producer.write(notif.payload)`. Top-level generic fields (`diaObjectId`, `ra`, `dec`, `catalog_name`, `catalog_source_id`, `separation_arcsec`) plus a nested `catalog_payload` object whose keys are the lowercased upstream-native column names declared in `settings.CROSSMATCH_CATALOGS[*].payload_columns`. Pinning the shape inline (not deferring to the implementer to reverse-engineer) directly resolves Success Criterion 1 — a cold reader can write a correct Hopskotch consumer schema from §4.6 alone. *(resolves OQ2 from origin)*

**KTD5 — Evolution policy: additive keys, no schema-version field.** §4.6 carries a one-sentence consumer-evolution callout: "Consumers must treat unknown `catalog_payload` keys as additive; new catalogs may add keys, and the published-payload contract is not versioned beyond what `catalog_name` discriminates." This is the cheapest honest answer to forward-compat — it acknowledges that adding a fifth catalog will add new keys without committing this refresh to introducing a schema version field. *(resolves OQ4 from origin, path (a))*

**KTD6 — §9 stays leaner than §4.6 deliberately.** The brainstorm's "no second-source drift" decision for §9 produces an asymmetric reader experience inside the same doc (§4.6 pins payload shape inline, §9 points outward). The plan preserves this asymmetry without surfacing it as a separate "deployment audience is different" prose note — the GitOps plan at `docs/plans/2026-06-02-001-feat-crossmatch-service-k8s-gitops-plan.md` is the right home for the deployment-side reader, and §9.1's one paragraph + the named pointer establishes that mental model. *(preserves OQ3 from origin; no in-plan change)*

---

## Implementation Units

### U1. §4.6 Notifier → SCiMMA Hopskotch — pin the canonical payload shape

**Goal:** Replace the §4.6 published-message example with the actual shape emitted by the service today, including the nested `catalog_payload` object, and add the additive-keys evolution callout and the two solution-doc cross-references.

**Requirements:** R1 (high-impact, the payload is the only external API), R15 (cross-references to `catalog-specific-payload-columns.md` and `coerce-numpy-pandas-scalars-to-json.md`).

**Dependencies:** None (this unit reads code; it does not depend on other units).

**Files:**
- Modify: `scimma_crossmatch_service_design.md` (§4.6, around the current "Message payload" example at the line currently containing the flat 6-field dict)
- Read for grounding (no edit): `crossmatch/tasks/crossmatch.py` (the publish dict is assembled at lines 120–132); `crossmatch/notifier/impl_hopskotch.py` (publishes the dict verbatim via `producer.write(notif.payload)`); `crossmatch/matching/payload.py` (the `build_catalog_payload` helper that fills the nested object); `crossmatch/project/settings.py` (`CROSSMATCH_CATALOGS[*].payload_columns` for per-catalog key examples)

**Approach:**
- The current §4.6 example shows a flat 6-key dict (`diaObjectId`, `ra`, `dec`, `catalog_name`, `catalog_source_id`, `separation_arcsec`). The shipped code adds a seventh top-level key, `catalog_payload`, whose value is an object built by `build_catalog_payload` — lowercased upstream-native column names mapped to JSON-native scalars (or `null` for missing values), with a stable key set per catalog.
- Replace the example with the full seven-key shape. Use one catalog (Gaia DR3 is the cleanest demo because it's already lowercase upstream) as the worked example, with three or four representative `catalog_payload` keys (e.g., `phot_g_mean_mag`, `parallax`, `pmra`, `ruwe`) — not the whole list — and a "…" continuation so the reader sees the shape without the example bloating.
- Add a brief prose paragraph noting:
  - The top-level keys (`diaObjectId` through `separation_arcsec`) are generic across all catalogs; `catalog_payload` is catalog-specific.
  - `catalog_payload` keys are the lowercased upstream-native names from `CROSSMATCH_CATALOGS[*].payload_columns` (case-mapped at publish time — e.g., DES `WAVG_MAG_PSF_G` becomes `wavg_mag_psf_g`; SkyMapper's `raj2000` is preserved because it's already lowercase).
  - Missing values appear as JSON `null`; the key set is stable per catalog regardless of per-row nulls.
- Add the evolution-policy sentence (per KTD5): "Consumers must treat unknown `catalog_payload` keys as additive; new catalogs may add keys without a schema-version bump, and the contract is discriminated by `catalog_name` rather than a version field."
- Add two cross-references at the end of §4.6 (or in a small "See also" inline block): `docs/solutions/conventions/catalog-specific-payload-columns.md` (the declarative `payload_columns` config convention) and `docs/solutions/design-patterns/coerce-numpy-pandas-scalars-to-json.md` (the numpy/pandas → JSON-native boundary handling, including the `pd.isna` sentinel coverage and bool-before-int rule).

**Patterns to follow:** The brainstorm's own description of the payload shape (in OQ2 of the origin doc) and the canonical example assembled in `crossmatch/tasks/crossmatch.py` lines 120–132 — the example dict in §4.6 should match that construction key-for-key (with `catalog_payload` flattened as shown by `build_catalog_payload`).

**Test scenarios:** None — pure documentation edit, no behavioral change. Manual verification only:
- After edit, the §4.6 example dict has exactly seven top-level keys and the nested `catalog_payload` object is present.
- The example's keys match the keys constructed at `crossmatch/tasks/crossmatch.py:123-131`.
- Both cross-referenced solution docs exist at the paths listed.
- The evolution-policy sentence is present.

**Verification:** A cold reader of the refreshed §4.6 can write a JSON-consumer schema covering: seven top-level keys, the nested `catalog_payload` shape, the additive-keys evolution policy, and the discrimination by `catalog_name`. Spot-check: searching the design doc for the pre-refresh example phrase (`"separation_arcsec": 0.42`) returns one match — the new example — not a stale duplicate.

---

### U2. Targeted single-section corrections — §7.1 snippet, §5.2.1b table, §2.1 D notifier, §9.1.2 Helm chart

**Goal:** Apply the four high-impact corrections where the current doc actively misleads a reader, each scoped to a single section.

**Requirements:** R2 (§7.1 `_get_catalog` snippet), R3 (§5.2.1b `alert_deliveries` table), R4 (§2.1 D Match Notifier description), R5 (§9.1.2 Helm chart name).

**Dependencies:** None (each correction is independent; they're bundled in one unit because each is small).

**Files:**
- Modify: `scimma_crossmatch_service_design.md` (§7.1 around the current `_get_catalog` code block; §5.2.1b table at the `alert_deliveries` heading; §2.1 D Match Notifier subsection; §9.1.2 Helm chart approach subsection)
- Read for grounding (no edit): `crossmatch/matching/catalog.py` (current `_get_catalog` at lines 37–74 — this is the source for R2's snippet); `crossmatch/core/models.py` (`AlertDelivery` model at the relevant class — actual fields are `id`, `alert`, `broker`, `ingest_time` — this is the source for R3's table); `kubernetes/charts/crossmatch-service/Chart.yaml` (confirms R5's chart name)

**Approach:**
- **§7.1 (R2):** Replace the cached snippet (currently showing a three-column-only `_get_catalog`) with the current `crossmatch/matching/catalog.py:37-74` body. The new snippet includes `_ALERT_COLUMNS` collision detection, the `columns="all"` schema introspection and missing-column validation, and the load of `payload_columns` alongside the source-id/RA/Dec triple. Keep the existing `crossmatch_alerts(..., suffix_method='overlapping_columns')` call (still current — confirmed during research).
- **§5.2.1b (R3):** In the documented table, remove the rows for `broker_alert_id`, `delivered_at`, and `raw_payload`. The actual model carries `id` (BIGSERIAL PK), `alert` (FK to `alerts(lsst_diaObject_diaObjectId)`), `broker` (TEXT), and `ingest_time` (TIMESTAMPTZ, set by `auto_now_add=True`). Update the broker-enum documentation from `'antares' or 'lasair'` to `'antares' or 'lasair' or 'pittgoogle'`. The UNIQUE constraint `(lsst_diaobject_diaobjectid, broker)` stays.
- **§2.1 D (R4):** Replace "Sends an update/annotation back to LSST (mechanism TBD)" with "Publishes match payloads over Hopskotch (Kafka via hop-client; see §4.6). The LSST return channel (§4.5) remains TBD." Preserve the bookkeeping bullet about `notifications` records and retries.
- **§9.1.2 (R5):** Find references to a planned `alertmatch` chart. Replace the chart name with `crossmatch-service`. Change "We will create a top-level Helm chart `alertmatch` that deploys:" to "The Helm chart at `kubernetes/charts/crossmatch-service/` deploys:" (or similar present-tense phrasing). The list of deployed services below the chart-creation sentence stays.

**Patterns to follow:** For each section, the corrected content is fully derivable from the cited code/manifest source — no judgment calls. Match the surrounding prose voice in the design doc (concise, declarative).

**Test scenarios:** None — pure documentation edit. Manual verification per correction:
- §7.1: the new snippet's `_ALERT_COLUMNS` set, `columns="all"` introspection, and missing-column `ValueError` are all present and match `crossmatch/matching/catalog.py` lines 18, 62, 64.
- §5.2.1b: the documented table has exactly four columns (`id`, `lsst_diaobject_diaobjectid` FK, `broker`, `ingest_time`); the broker-enum description lists three values.
- §2.1 D: Hopskotch is named explicitly; §4.6 is referenced; LSST return remains TBD.
- §9.1.2: the `alertmatch` string no longer appears; `kubernetes/charts/crossmatch-service/` is referenced; present-tense voice.

**Verification:** A reader following the design doc can find the `AlertDelivery` schema in §5.2.1b and have it match what they see in `crossmatch/core/models.py`. The §7.1 code block reads as a current snippet, not a draft. A reader looking for "where do matches go" lands on Hopskotch via §2.1 D. A new contributor doesn't get confused looking for an `alertmatch` Helm chart that doesn't exist.

---

### U3. Catalog roster generalization + §3.1 sequence diagram + §7.3 asymmetry callout

**Goal:** Generalize the catalog enumerations across the doc per KTD3, refresh the sequence diagram to show Pitt-Google and Hopskotch alongside the existing flows, and concentrate per-catalog asymmetries in a single §7.3 callout so the generalization doesn't erase detail a reader needs.

**Requirements:** R6 (catalog count drift), R7 (sequence diagram refresh), R8 (catalog config schema + asymmetry callout).

**Dependencies:** None.

**Files:**
- Modify: `scimma_crossmatch_service_design.md` (§2.1 C the Crossmatch Workers description, §3 step 4, §3.1 mermaid sequence diagram, §7.3 Catalog Registry, §8.4 task definitions, §11.1 first milestone — preserving §11.1's historical framing per Scope Boundaries)

**Approach:**
- **§2.1 C, §3 step 4, §8.4 (R6):** Replace each "Gaia DR3 and DES Y6 Gold" enumeration with "all configured HATS catalogs" or "all entries in `CROSSMATCH_CATALOGS`" depending on which reads more naturally per occurrence. §11.1 stays as-is (historical first-milestone marker — see Scope Boundaries).
- **§3.1 sequence diagram (R7):** The current diagram shows ANTARES and Lasair branches, an `LSDB (Gaia, DES)` participant, and an `LSST Update Receiver (TBD)` placeholder. Three changes:
  1. Add a Pitt-Google branch parallel to ANTARES and Lasair, mirroring the structure in §2.1 B3 and §4.4 (Pub/Sub subscription, SMT UDF filter, ingest service, UPSERT into `alerts` + `alert_deliveries`, conditional task enqueue on new-alert path).
  2. Relabel the `LSDB (Gaia, DES)` participant to `LSDB (HATS catalogs)` — generic, matching the body of the doc post-R6.
  3. Add Hopskotch as a participant. Show the notifier publishing to it (mirror §4.6 publish lifecycle: `dispatch_notifications` polls pending → groups by destination → routes via `notifier/dispatch.py` → Hopskotch handler publishes). The LSST Update Receiver placeholder stays.
- **§7.3 (R8):** Two parts:
  1. Add `payload_columns` to the per-catalog config schema documented in the prose (currently the schema is named as `name`, `hats_url`, `source_id_column`, `ra_column`, `dec_column`). Update the "Adding a new catalog requires only a new entry…" sentence to add: "…with `payload_columns` declared in upstream-native case and validated against `docs/references/<catalog>-columns.md` before merge."
  2. Add the asymmetry callout immediately after the four-catalog enumeration. Cover: the case-convention split (Gaia/SkyMapper lowercase, DES/DELVE UPPERCASE; SkyMapper's coordinates carry a J2000 suffix `raj2000`/`dej2000` preserved end-to-end), the partial-footprint reality (`crossmatch` raises `RuntimeError("Catalogs do not overlap")` when a catalog's footprint misses the batch — handled by the task loop as a normal no-match case; DES Y6 Gold yields no matches outside its southern footprint, etc.), per-catalog `payload_columns` divergence (Gaia has parallax/proper-motion, DES and DELVE have shape and photo-z, DELVE drops DES's Y band, SkyMapper exposes only PSF photometry), and margin-cache availability differences (the existing "Margin Caches and Edge Effects" subsection in §7.1 has a table — point to it rather than duplicate).

**Patterns to follow:** The existing §7.3 prose for `payload_columns` mirrors the brainstorm-confirmed "catalog-specific declarative publish contract" framing — language can come from `docs/solutions/conventions/catalog-specific-payload-columns.md` (the recently committed doc). For the mermaid sequence diagram changes, mirror the existing par/alt block structure for ANTARES and Lasair branches.

**Test scenarios:** None — pure documentation edit. Manual verification:
- Spot check per KTD3: `grep -n 'Gaia DR3 and DES Y6 Gold' scimma_crossmatch_service_design.md` returns either zero matches or only §11.1's historical reference.
- §3.1 mermaid block parses (renders as a valid sequence diagram) and contains a Pitt-Google participant + branch and a Hopskotch participant. Re-render preview if mermaid tooling is available.
- §7.3 schema has six fields documented (the previous five plus `payload_columns`); the asymmetry callout names all four asymmetry classes (case, footprint, payload columns, margin caches).

**Verification:** A reader looking for the live catalog roster lands on §7.3 with all four catalogs enumerated authoritatively and with the asymmetry classes spelled out. The §3.1 sequence diagram shows all three brokers and both output channels (Hopskotch live, LSST return TBD). The "all configured HATS catalogs" phrasing in §2.1/§3/§8.4 survives the next catalog addition without further edit.

---

### U4. Module layout drift — §8.2 package layout + §8.3 key processes

**Goal:** Refresh the documented Python module/file tree and long-lived process list to match the current code.

**Requirements:** R10 (§8.2 package layout), R11 (§8.3 key processes).

**Dependencies:** None.

**Files:**
- Modify: `scimma_crossmatch_service_design.md` (§8.2 the package-layout tree, §8.3 the key-processes list)
- Read for grounding (no edit): the actual directory contents — `crossmatch/brokers/{antares,lasair,pittgoogle}`, `crossmatch/brokers/normalize.py`, `crossmatch/matching/{catalog.py,payload.py}`, `crossmatch/notifier/{dispatch,impl_hopskotch,impl_http,lsst_return,watch}.py`, and `crossmatch/project/management/commands/run_{antares,lasair,pittgoogle}_ingest.py`

**Approach:**
- **§8.2 (R10):** Edit the package-layout tree:
  - `brokers/` — list `antares/`, `lasair/`, `pittgoogle/` as subdirectories AND `normalize.py` at the top level (the shared LSST field extraction helper). Drop the "TARGET LAYOUT — current code has antares/ at top level pending this refactor" comment; the refactor is done.
  - `matching/` — list `catalog.py` and `payload.py` (the latter is missing from the current doc).
  - `notifier/` — list `dispatch.py`, `impl_hopskotch.py`, `impl_http.py`, `lsst_return.py`, `watch.py` (current doc lists only three of these).
- **§8.3 (R11):** Add a new bullet `python manage.py run_pittgoogle_ingest` to the long-lived-processes list alongside the existing `run_antares_ingest` and `run_lasair_ingest` entries.

**Patterns to follow:** The existing tree style in §8.2 (indented bullets / file paths). The existing process-list style in §8.3 (one bullet per command).

**Test scenarios:** None — pure documentation edit. Manual verification:
- The §8.2 tree includes every file/directory listed under the "Read for grounding" entry above; nothing in that list is missing.
- The §8.2 "TARGET LAYOUT" comment is gone.
- §8.3 lists the Pitt-Google ingest command.

**Verification:** A new contributor reading §8.2 to navigate the code finds every module that exists in the repo. A reader looking for "how do I run the Pitt-Google ingest" finds the command in §8.3.

---

### U5. Deployment paragraph + env-var catalog + LSDB version + remaining cross-references

**Goal:** Introduce the k8s GitOps approach in a single §9.1 paragraph (R12 + R13 co-located), extend the §9.1.3 env-var catalog, name the LSDB pinned version in §7.4 with the dep-pin convention cross-reference, and add the remaining solution-doc cross-reference in §5.2.

**Requirements:** R9 (§9.1.3 env-var catalog), R12 (§9 GitOps paragraph), R13 (§9 env-var contract guardrail), R14 (§7.4 LSDB version + dep-pin cross-ref), R15-rest (§5.2 dev-DB cross-ref).

**Dependencies:** None.

**Files:**
- Modify: `scimma_crossmatch_service_design.md` (new paragraph in §9.1; extend §9.1.3 env-var table; §7.4 prose where the pinning rationale lives; cross-reference near §5.2 or §11 — implementer's choice per the brainstorm)
- Read for grounding (no edit): `.github/workflows/build-image.yml` (confirms image-publish flow); `deploy-contract.yaml` (the env-var contract artifact); `docs/plans/2026-06-02-001-feat-crossmatch-service-k8s-gitops-plan.md` (the authoritative GitOps plan to link); `crossmatch/requirements.base.txt` (current LSDB version pin); `crossmatch/project/settings.py` and §4.4 / §4.6 of the design doc (for the env-var entries to add)

**Approach:**
- **§9.1 GitOps paragraph (R12 + R13 co-located per Success Criterion 3):** Add one paragraph in §9.1 (not §9.1.2 — the Helm chart subsection — but at the §9.1 introductory level, before the §9.1.1 deployments listing). The paragraph names:
  - The `crossmatch-service-k8s-gitops` repo at GitLab as the home of the Helm values overlay.
  - The image publish: `.github/workflows/build-image.yml` in *this* repo publishes the container image to the public GitLab Container Registry on semver tags; the Jetstream2 cluster pulls anonymously (no pull secret required).
  - The deploy env-var contract: `deploy-contract.yaml` (in this repo) is the source of truth for the env-var surface between this service and the gitops chart; the contract is enforced at build/deploy time as a guardrail (PR #45).
  - The link to the authoritative GitOps plan: `docs/plans/2026-06-02-001-feat-crossmatch-service-k8s-gitops-plan.md`.
  - Per KTD2, do **not** port mechanics (registry choice rationale, sealed-secret arrangement, Helm overlay shape) into this paragraph.
- **§9.1.3 env-var catalog (R9):** Extend the existing env-var table with rows for:
  - `MIN_DIASOURCE_RELIABILITY` (broker filter standard threshold; covered in §2.2)
  - The Pitt-Google set: `PITTGOOGLE_TOPIC`, `PITTGOOGLE_SUBSCRIPTION`, `PITTGOOGLE_PUBLISHER_PROJECT`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_APPLICATION_CREDENTIALS` (covered in §4.4)
  - The Hopskotch set: `HOPSKOTCH_BROKER_URL`, `HOPSKOTCH_TOPIC`, `HOPSKOTCH_USERNAME`, `HOPSKOTCH_PASSWORD` (covered in §4.6)
  - The remaining HATS URLs: `DELVE_HATS_URL`, `SKYMAPPER_HATS_URL` (matching the existing `GAIA_HATS_URL` and `DES_HATS_URL` entries)
  Each row carries a "see §X" cross-reference rather than duplicating the topical context. Group entries by feature area (broker-filter / Pitt-Google / Hopskotch / catalog URLs) for navigability.
- **§7.4 (R14):** In the prose where the pinning rationale lives, name the current LSDB pinned version explicitly: "LSDB is currently pinned at v0.9.0 (see `crossmatch/requirements.base.txt`)." Add a cross-reference at the end of the rationale: "For the convention used when bumping LSDB or any cluster-aligned pin atomically, see `docs/solutions/conventions/dependency-pin-upgrade-pattern-2026-05-12.md`."
- **§5.2 dev-DB cross-reference (R15-rest):** Add a one-line cross-reference near §5.2 (or in a §11 appendix, implementer's choice) pointing readers to `docs/solutions/developer-experience/query-dev-database-via-docker-exec.md` — relevant for anyone running ad-hoc SQL against the dev DB while debugging or prototyping.

**Patterns to follow:** The existing §9.1.3 env-var table format (variable name | example value | notes column). The brainstorm's confirmed phrasing for the GitOps paragraph (KTD2). For the LSDB version line in §7.4, mirror the surrounding voice (declarative, name-the-decision).

**Test scenarios:** None — pure documentation edit. Manual verification:
- §9.1 has one new paragraph naming all four elements above and links the GitOps plan path.
- §9.1.3 table has 11 new rows (1 + 5 + 4 + 1 — minus any already present; verify against the current table before adding to avoid duplicates).
- §7.4 names "v0.9.0" and cross-references the dep-pin convention doc.
- §5.2 (or §11) has a one-line dev-DB cross-reference.
- Success Criterion 3 spot-check: "within one paragraph of §9" — the gitops repo, GitOps plan, image registry, AND env-var contract guardrail all appear in the same §9.1 paragraph, not split across paragraphs.

**Verification:** A reader interested in deployment lands on §9.1's first paragraph, gets the four anchors (gitops repo, image publish path, env-var contract, GitOps plan), and is one click away from full details in the gitops repo or the plan. A reader inspecting `.env` while running locally finds every env-var in §9.1.3. A maintainer bumping LSDB finds the convention doc cross-reference in §7.4.

---

## Scope Boundaries

Carried verbatim from origin where applicable; *Deferred to Follow-Up Work* is plan-local.

- **No code changes.** `AlertDelivery` model fields stay as-is; the stale `# 'antares' | 'lasair'` comment in `crossmatch/core/models.py` is not in scope for this plan. *(see origin)*
- **No new section on k8s GitOps mechanics.** A short pointer in §9.1 only; full deployment details stay in the gitops repo and `docs/plans/2026-06-02-001-feat-crossmatch-service-k8s-gitops-plan.md`. *(see origin; KTD2)*
- **§10 *Open Questions* stays as-is** beyond moving any newly-resolved items into the existing resolved-strikethrough convention. Adding new open questions to §10 is out of scope. *(see origin)*
- **§11.1 *Suggested first implementation milestone* stays as-is.** It reads as a historical first-milestone marker. *(see origin)*
- **No full rewrite.** The refresh is targeted to the gaps identified in the requirements, not a structural reorganization. *(see origin)*

### Deferred to Follow-Up Work

- **OQ1 from origin — Stale `# 'antares' | 'lasair'` comment in `crossmatch/core/models.py:64`.** Routed here per KTD1 to preserve the no-code-changes scope of this refresh. Suggested follow-up: a separate single-line PR (`docs: update AlertDelivery.broker comment to include pittgoogle`) or a docs/solutions entry recording the source-of-truth gap. *(reviewer-flagged; product-lens + adversarial residual risks)*

---

## Open Questions

### Deferred to Implementation

- **OQ-Plan-1 — Where exactly does the dev-DB cross-reference (R15-rest) land?** R15 names "§5.2 (or §11 appendices, planner's choice)" — the choice between adjacent-to-the-dev-DB-discussion versus appendix is the implementer's call based on what reads better in context. The plan does not pre-resolve this.
- **OQ-Plan-2 — How to express the deferred idempotency-and-replay intent from KTD1.** The brainstorm's Key Decisions establish that the design doc's prior `broker_alert_id` / `raw_payload` / `delivered_at` fields encoded an idempotency-and-replay intent that the as-built model does not preserve. The plan respects KTD1 (doc reflects as-built, intent recorded). The implementer can record the deferred intent inline (a sentence in §5.2.1b noting that the original design intent for `alert_deliveries` is captured in the brainstorm's Deferred / Open Questions section) or omit it from the doc entirely and rely on the brainstorm/this-plan trail. Default: inline sentence — but cheap to omit if it reads as clutter.

### Deferred to Future Brainstorm / Plan

- **OQ3 from origin — §9 pointer-only audience asymmetry** (reviewer-flagged but not resolved this round). Preserved as a deferred product judgment; this plan honors the brainstorm's "short pointer" decision.
- **OQ4 from origin — Hopskotch payload schema versioning beyond the additive-keys callout.** Adopted path (a) in KTD5 (additive-keys policy as a §4.6 callout). If a future schema-version field is wanted, that's its own brainstorm.

---

## System-Wide Impact

This plan modifies a single file (`scimma_crossmatch_service_design.md`). No code, no migrations, no deployment config, no test changes. Affected audiences:

- **External downstream consumers of the Hopskotch stream:** the only audience that reads §4.6's payload example as a build contract. U1's edit changes their mental model from "flat 6-key dict" to "7-key dict with nested catalog_payload." Properly executed, this aligns the doc with what they were already receiving on the wire (the publish code emits the seven-key shape today regardless of doc state); incorrectly executed (wrong shape pinned), it would mislead consumers in a new way.
- **Internal contributors and reviewers:** §2.1 / §3 / §3.1 / §7 / §8 readers. The refresh lowers their friction (correct module layout, current code snippet, accurate catalog roster) without breaking any existing internal contract.
- **Deployment / SRE readers:** §9 audience. The new §9.1 paragraph gives them the cross-repo anchors (gitops repo, image registry, env-var contract guardrail, plan).
- **Maintainers bumping LSDB or other cluster-aligned pins:** §7.4 cross-reference to the dep-pin convention doc.

No external systems are touched.

---

## Risks & Dependencies

### Risks

- **R-1 (U1) — Pinning the wrong Hopskotch payload shape.** The doc would mislead consumers more authoritatively than it does today. Mitigation: U1's Approach pins the source-of-truth files (`crossmatch/tasks/crossmatch.py` lines 120-132 and `crossmatch/notifier/impl_hopskotch.py:32`); the verification step explicitly compares the documented example against the construction in code. This risk should be eliminated by careful execution but warrants a second read before merge.
- **R-2 (U3) — §3.1 mermaid syntax errors.** Adding a Pitt-Google branch and a Hopskotch participant means editing a substantial mermaid block. A syntax error would break diagram rendering on GitHub and in any other markdown viewer. Mitigation: render the mermaid block locally or in a previewer (mermaid.live, GitHub preview) after editing.
- **R-3 (U5) — Duplicate env-var entries in §9.1.3.** Some entries may already be partially present in the table; adding without checking would create duplicates. Mitigation: U5's verification step explicitly says "verify against the current table before adding to avoid duplicates."
- **R-4 (U2) — Removing `delivered_at` / `raw_payload` may break readers' mental models elsewhere.** The §5.2.3 `crossmatch_runs` table and §5.2.4 `notifications` discussion may reference `alert_deliveries` semantics that imply those fields. Mitigation: U2 reviewer should grep the design doc for references to the removed fields after the §5.2.1b edit and update them in the same commit if found. (Quick check during planning: a grep for `broker_alert_id` and `raw_payload` against the current design doc shows references only in §5.2.1b's table itself — no other section cites these fields. Low residual risk.)

### Dependencies

- **`docs/plans/2026-06-02-001-feat-crossmatch-service-k8s-gitops-plan.md` must remain at its current path** — U5's §9.1 paragraph links it. If the gitops plan is renamed or moved before this plan executes, U5's link will need to be updated. (Verified present at planning time.)
- **`deploy-contract.yaml` must remain at the repo root.** Same caveat. (Verified present at planning time.)
- **The four `docs/solutions/` cross-references (across U1, U5) must remain at their current paths.** All four were committed on the `feature/document-catalog-payload-solutions` branch earlier this session. (Verified present at planning time.)
- **No upstream changes to `crossmatch/tasks/crossmatch.py` or `crossmatch/notifier/impl_hopskotch.py` between plan-write and execution.** If the publish dict construction changes before U1 lands, U1 must re-derive the shape. (Low risk; the catalog-specific-payload work just landed and is stable.)

---

## Sources & Research

- **Origin requirements:** `docs/brainstorms/2026-06-12-refresh-service-design-doc-requirements.md` (15 requirements, four KTDs, scope boundaries, four OQ entries).
- **Origin doc-review pass:** Applied 3 silent + 4 walk-through fixes during the brainstorm review; deferred 4 to the brainstorm's Open Questions (OQ1–OQ4) which this plan inherits.
- **Code grounding for U1 (Hopskotch payload shape):**
  - `crossmatch/tasks/crossmatch.py` lines 120–132 — Notification.payload construction (the seven-key shape with nested `catalog_payload`).
  - `crossmatch/notifier/impl_hopskotch.py` line 32 — `producer.write(notif.payload)` publishes the dict verbatim.
  - `crossmatch/matching/payload.py` — `build_catalog_payload(values, payload_columns)` fills `catalog_payload`.
  - `crossmatch/project/settings.py` — `CROSSMATCH_CATALOGS[*].payload_columns` defines per-catalog key sets.
- **Code grounding for U2:**
  - `crossmatch/matching/catalog.py` lines 18, 21–34, 37–74 — current `_get_catalog`, `_ALERT_COLUMNS`, `_load_columns`, validation pattern.
  - `crossmatch/core/models.py` — `AlertDelivery` model actual fields (`id`, `alert`, `broker`, `ingest_time`).
  - `kubernetes/charts/crossmatch-service/Chart.yaml` — actual Helm chart name/location.
- **Code grounding for U4 (module layout):** directory listings of `crossmatch/brokers/`, `crossmatch/matching/`, `crossmatch/notifier/`, `crossmatch/project/management/commands/` (verified at planning time).
- **Code grounding for U5:**
  - `.github/workflows/build-image.yml` — image-publish pipeline, registry choice context.
  - `deploy-contract.yaml` — env-var contract artifact at repo root.
  - `crossmatch/requirements.base.txt` — LSDB version pin (currently `lsdb==0.9.0`).
- **Cross-referenced solution docs (must remain at these paths):**
  - `docs/solutions/conventions/catalog-specific-payload-columns.md`
  - `docs/solutions/design-patterns/coerce-numpy-pandas-scalars-to-json.md`
  - `docs/solutions/developer-experience/query-dev-database-via-docker-exec.md`
  - `docs/solutions/conventions/dependency-pin-upgrade-pattern-2026-05-12.md`
- **Cross-referenced plan (must remain at this path):** `docs/plans/2026-06-02-001-feat-crossmatch-service-k8s-gitops-plan.md`.
