---
date: 2026-06-12
topic: refresh-service-design-doc
---

# Refresh `scimma_crossmatch_service_design.md` against recent work

## Summary

Align the service architecture design doc with work landed since 2026-04-27: per-catalog payload columns, the four-catalog roster, Pitt-Google in diagrams and enums, the current Python module/file layout, the Hopskotch payload shape, the as-built `alert_deliveries` model, the real Helm chart name, and a short pointer to the k8s GitOps repo and plan.

## Problem Frame

`scimma_crossmatch_service_design.md` was last edited on 2026-04-27 (`5e77ca4 docs(broker-filter): standardize broker filter on reliability >= 0.6`). The roughly six weeks since have carried substantive work that the doc does not yet reflect: catalog-specific payload columns (PR #44), the LSDB v0.9.0 upgrade (PR #42), and the k8s GitOps + image-publishing track (PRs #45–53), plus three new `docs/solutions/` docs from the most recent session.

The doc still tells a reader things that are wrong (the Hopskotch payload shape, the broker enum, the Helm chart name, the "TARGET LAYOUT" refactor comment), enumerates two catalogs in several places when four are live, and shows a code snippet for `_get_catalog` that predates the schema validation and collision guard. A fresh reader following the doc would build the wrong consumer schema and would not find the four `docs/solutions/` references (three new from the most recent session, plus the older `dependency-pin-upgrade-pattern-2026-05-12.md` convention doc that backs the version-pinning rationale) when implementing in the area.

The refresh is a doc-only change. Code is the source of truth; where the doc and the model disagree (most visibly in §5.2.1b `alert_deliveries` fields), the doc gets trimmed to match the model rather than the model getting catching-up changes.

## Key Decisions

**Doc reflects as-built; no code changes.** Where the design doc currently describes fields or interfaces that don't exist in the code (e.g., `AlertDelivery.broker_alert_id`, `AlertDelivery.raw_payload`, `AlertDelivery.delivered_at`), the doc gets trimmed to match. Those fields encoded an idempotency-and-replay intent (per-broker alert id, raw broker envelope, separate delivery timestamp distinct from ingest time) that the as-built model does not preserve — this brainstorm explicitly defers, not resolves, that gap. The deferred intent is captured in the *Deferred / Open Questions* section below for `/ce-plan` or a follow-up brainstorm to act on. Catching up the model (or its inline comments) is a separate task whose scope and timing should be decided on its own merits, not bundled into a doc audit.

**K8s GitOps stays out of this doc beyond a short pointer.** PRs #45–53 landed a substantial deployment story across two repos (this one + `crossmatch-service-k8s-gitops` on GitLab) with its own implementation plan (`docs/plans/2026-06-02-001-feat-crossmatch-service-k8s-gitops-plan.md`). §9 of the design doc gets a paragraph naming the gitops repo, the image registry, the deploy env-var contract, and the GitOps plan path — and links out. Reproducing the full mechanics here would create the second-source drift the original design doc is already suffering from.

**Generalize catalog enumerations.** Where the doc currently lists "Gaia DR3 and DES Y6 Gold" in service descriptions (§2.1 C, §3, §3.1, §8.4, §11.1), prefer abstract phrasing ("all configured HATS catalogs" or "all entries in `CROSSMATCH_CATALOGS`") with a single authoritative four-catalog list in §7.3. Reduces drift the next time a catalog is added.

## Requirements

### High-impact corrections (the doc actively misleads a reader today)

**R1.** §4.6 *Notifier → SCiMMA Hopskotch* — update the published-message example to reflect the catalog-specific payload contract. The example must show that each message includes the catalog-specific scientific fields under a `catalog_payload` key (or whatever shape the current publishing code emits, as derived from the source), with lowercased keys and JSON-native scalars. Cross-reference `docs/solutions/conventions/catalog-specific-payload-columns.md` and `docs/solutions/design-patterns/coerce-numpy-pandas-scalars-to-json.md` for full detail.

**R2.** §7.1 *LSDB Native Batch Crossmatching* — replace the `_get_catalog` code snippet with the current version, which validates requested columns against `columns="all"`, blocks alert-column collisions via `_ALERT_COLUMNS`, and loads `payload_columns` alongside the source-id / RA / Dec triple.

**R3.** §5.2.1b *alert_deliveries* — bring the table description into line with the actual `AlertDelivery` model in `crossmatch/core/models.py`. Remove `broker_alert_id`, `delivered_at`, and `raw_payload` from the documented table; the actual model has `ingest_time` (set by `auto_now_add=True`) in place of any of those. Add `'pittgoogle'` to the documented broker enum values.

**R4.** §2.1 D *Match Notifier Service* — replace "Sends an update/annotation back to LSST (mechanism TBD)" with a description that names Hopskotch as the live primary output channel, with the LSST return channel remaining TBD. Cross-reference §4.6.

**R5.** §9.1.2 *Helm chart approach* — replace references to a planned `alertmatch` chart with the actual `crossmatch-service` chart at `kubernetes/charts/crossmatch-service/`. Switch the prose from future-tense ("We will create…") to present-tense ("Deploys…").

### Stale specifics (medium impact)

**R6.** Catalog count drift across the doc. In §2.1 C, §3 step 4, §8.4, and §11.1, generalize references to "all configured HATS catalogs" per the Key Decision above. In §3.1 the sequence-diagram participant label `LSDB (Gaia, DES)` becomes either a generic `LSDB (HATS catalogs)` label or the full four-catalog list. The authoritative four-catalog enumeration stays in §7.3.

**R7.** §3.1 *Sequence Diagram* — add a Pitt-Google branch alongside ANTARES and Lasair (mirroring §2.1 B3 and §4.4). Add Hopskotch as a participant and show the notifier publishing to it alongside the placeholder LSST Update Receiver.

**R8.** §7.3 *Catalog Registry and Expansion* — add `payload_columns` to the documented per-catalog config schema. Update "Adding a new catalog requires only a new entry…" to include declaring `payload_columns` and validating the chosen columns against `docs/references/<catalog>-columns.md`. Add a single "catalogs are not symmetric" callout in §7.3 covering: the upstream-native case rule (Gaia/SkyMapper lowercase, DES/DELVE UPPERCASE, SkyMapper's J2000 suffix), the partial-footprint reality (no-overlap raises "Catalogs do not overlap" and is normal — e.g., DES Y6 Gold misses the northern footprint), per-catalog `payload_columns` divergence, and margin-cache availability differences. This absorbs the symmetry-vs-asymmetry trade-off introduced by the catalog-enumeration generalization (R6 / Key Decisions) without re-introducing per-section drift.

**R9.** §9.1.3 *Configuration & secrets* env-var catalog — extend the list to include `MIN_DIASOURCE_RELIABILITY`, all `PITTGOOGLE_*` and `GOOGLE_*` Pitt-Google env vars, `HOPSKOTCH_BROKER_URL` / `HOPSKOTCH_TOPIC` / `HOPSKOTCH_USERNAME` / `HOPSKOTCH_PASSWORD`, and `DELVE_HATS_URL` / `SKYMAPPER_HATS_URL`. Cross-reference the topical sections rather than duplicating context.

### Module layout drift

**R10.** §8.2 *Suggested package layout* — refresh the `brokers/`, `matching/`, and `notifier/` subtrees to match the current code:

- `brokers/` contains `antares/`, `lasair/`, `pittgoogle/`, and `normalize.py` (shared LSST field extraction at the top level). Drop the "TARGET LAYOUT — current code has antares/ at top level pending this refactor" comment; the refactor is done.
- `matching/` contains `catalog.py` and `payload.py`.
- `notifier/` contains `dispatch.py`, `impl_hopskotch.py`, `impl_http.py`, `lsst_return.py`, `watch.py`.

**R11.** §8.3 *Key processes* — add `python manage.py run_pittgoogle_ingest` to the list of long-lived processes.

### Topics absent entirely

**R12.** §9 *Deployment* — add a paragraph in §9.1 introducing the k8s GitOps approach: the `crossmatch-service-k8s-gitops` repo at GitLab holds the Helm values overlay; this repo's `.github/workflows/build-image.yml` publishes the image to the public GitLab Container Registry on semver tags; the cluster pulls the image anonymously (no pull secret). Name and link `docs/plans/2026-06-02-001-feat-crossmatch-service-k8s-gitops-plan.md` as the authoritative source. Do not port mechanics (registry choice rationale, sealed-secret arrangement, Helm overlay shape) into this doc.

**R13.** §9 *Deployment* — name the deploy env-var contract guardrail (PR #45) and link the implementation, so a reader knows the env-var surface between this service and the gitops chart is enforced rather than ambient. Co-locate this content with R12's gitops-repo pointer in a single §9.1 paragraph so Success Criterion 3 ("within one paragraph of §9") is satisfied.

**R14.** §7.4 *Dask Cluster Requirements* — name the current pinned LSDB version (0.9.0) in the prose where the version-pinning rationale lives, and cross-reference `docs/solutions/conventions/dependency-pin-upgrade-pattern-2026-05-12.md` so a reader maintaining the pins finds the convention doc.

**R15.** Add cross-references to the three new `docs/solutions/` docs from the design-doc sections they support:

- §4.6 and §7 → `docs/solutions/conventions/catalog-specific-payload-columns.md` and `docs/solutions/design-patterns/coerce-numpy-pandas-scalars-to-json.md`.
- §5.2 (or §11 appendices, planner's choice) → `docs/solutions/developer-experience/query-dev-database-via-docker-exec.md`, near the dev-database discussion.

## Success Criteria

- A reader who builds against the design doc cold can write a correct Hopskotch consumer schema, can find the four live catalogs, and can find the current module layout — without cross-referencing the code.
- A maintainer following the design doc to add a fifth catalog finds the `payload_columns` step named.
- A reader interested in deployment mechanics is pointed at the gitops repo and the GitOps plan within one paragraph of §9.
- The doc no longer disagrees with the as-built model in §5.2.1b.
- Spot check: `grep -n 'Gaia DR3 and DES Y6 Gold' scimma_crossmatch_service_design.md` returns either zero matches or only references that are intentionally historical (§11.1 first milestone).

## Scope Boundaries

- **No code changes.** `AlertDelivery` model fields stay as-is; the stale `# 'antares' | 'lasair'` comment in `crossmatch/core/models.py` is not in scope. If the maintainer wants the model to grow `broker_alert_id` / `raw_payload`, that is a separate planning artifact.
- **No new section on k8s GitOps mechanics.** A short pointer in §9 only; full deployment details stay in the gitops repo and `docs/plans/2026-06-02-001-feat-crossmatch-service-k8s-gitops-plan.md`.
- **§10 *Open Questions* stays as-is** beyond moving any newly-resolved items into the existing resolved-strikethrough convention. Adding new open questions is out of scope; surfacing them is brainstorm territory, not a doc-refresh task.
- **§11.1 *Suggested first implementation milestone* stays as-is.** It reads as a historical first-milestone marker; refreshing it would dilute that meaning.
- **No full rewrite.** The refresh is targeted to the gaps identified above, not a structural reorganization of the doc.

## Dependencies / Assumptions

- The `crossmatch-service-k8s-gitops` GitLab repo is the authoritative location for the deployment Helm overlay. (Verified against `.github/workflows/build-image.yml` in this repo.)
- `docs/plans/2026-06-02-001-feat-crossmatch-service-k8s-gitops-plan.md` is the authoritative implementation plan for the GitOps work. Maintainer to confirm this is still the document they want linked from §9 — if there is a newer or different deployment-of-record artifact, this should be updated during planning.
- The current published Hopskotch payload shape is derivable from code (`crossmatch/tasks/crossmatch.py` + `crossmatch/notifier/impl_hopskotch.py`); R1's example must be derived from that source, not from the existing design-doc example.

## Sources / Research

- The gap report produced in this brainstorm session (Phase 1.3 substance).
- Recent git history (`git log scimma_crossmatch_service_design.md` for the last-touched commit; `git log --since=2026-04-27` for work since).
- `crossmatch/core/models.py` — `AlertDelivery`, `CatalogMatch`, `Notification` shapes.
- `crossmatch/matching/catalog.py` — current `_get_catalog`, `_ALERT_COLUMNS`, validation pattern.
- `crossmatch/matching/payload.py` — `build_catalog_payload`, `_to_json_scalar`.
- `crossmatch/project/settings.py` — `CROSSMATCH_CATALOGS` with `payload_columns`.
- `crossmatch/brokers/{antares,lasair,pittgoogle}/consumer.py` — current broker module structure.
- `crossmatch/notifier/{dispatch,impl_hopskotch,impl_http,lsst_return,watch}.py` — current notifier module structure.
- `crossmatch/project/management/commands/run_{antares,lasair,pittgoogle}_ingest.py` — current ingest entry points.
- `crossmatch/tasks/crossmatch.py` — per-row payload build + lockstep `CatalogMatch` / `Notification` append; the published-payload shape originates here.
- `kubernetes/charts/crossmatch-service/Chart.yaml` — actual Helm chart name and location.
- `.github/workflows/build-image.yml` — image publish pipeline, registry choice context.
- `docs/plans/2026-06-02-001-feat-crossmatch-service-k8s-gitops-plan.md` — authoritative GitOps plan to link from §9.
- `docs/solutions/conventions/catalog-specific-payload-columns.md`, `docs/solutions/design-patterns/coerce-numpy-pandas-scalars-to-json.md`, `docs/solutions/developer-experience/query-dev-database-via-docker-exec.md` — the three new solution docs to cross-reference.
- `docs/solutions/conventions/dependency-pin-upgrade-pattern-2026-05-12.md` — convention to cross-reference from §7.4.

## Deferred / Open Questions

### From 2026-06-12 review

- **OQ1 — Stale `# 'antares' | 'lasair'` comment in `crossmatch/core/models.py:64`** *(P1, adversarial)*. R3 adds `'pittgoogle'` to the documented broker enum in the design doc, but Scope Boundaries leaves the contradicting in-source comment alone. A developer reading the code as source-of-truth lands on `# 'antares' | 'lasair'` and concludes Pitt-Google isn't supported — directly undercutting R3's broker-enum fix and the Problem Frame's "Code is the source of truth" principle. Decide between: (a) carve a narrow Scope Boundaries exception to update the one-line comment as part of this refresh (it's a comment, not behavior), or (b) explicitly record the comment as a known follow-up artifact (issue, separate plan, or `docs/solutions/` entry) so the source-of-truth contradiction is tracked rather than silently dropped.

- **OQ2 — R1 doesn't pin the canonical Hopskotch payload shape** *(P1, product-lens)*. Success Criterion 1 ("a reader who builds against the design doc cold can write a correct Hopskotch consumer schema") depends on R1 naming the canonical shape (top-level keys, where `catalog_payload` nests, what generic fields persist across all catalogs). R1 currently hedges: *"the catalog-specific scientific fields under a `catalog_payload` key (or whatever shape the current publishing code emits, as derived from the source)."* If the planner reads code loosely, the refresh ships and the cold-reader outcome silently misses. Decide whether to (a) read `crossmatch/tasks/crossmatch.py` + `crossmatch/notifier/impl_hopskotch.py` and tighten R1 to name the shape verbatim before planning, or (b) accept the planner deriving it from code during execution.

- **OQ3 — §9 pointer-only trade-off is asymmetric with §4.6** *(P2, product-lens)*. §4.6 (Hopskotch) pins the payload shape inline so a cold reader can act; §9 (Deployment) deliberately does the opposite — short pointer only, mechanics live in the gitops repo and the GitOps plan. Both choices are individually defensible, but the asymmetric reader experience inside the same document is not surfaced in Key Decisions. Decide between (a) acknowledge in Key Decisions that the deployment audience is a smaller, gitops-aware group expected to follow pointers (and §9 stays leaner deliberately), or (b) raise §9's bar to match §4.6 by including at least the env-var contract enforcement semantics and the image-publish trigger inline.

- **OQ4 — Hopskotch consumer success criterion underspecifies schema versioning and error-payload shape** *(P2, adversarial)*. Even with R1 tightened, a consumer cold-building from the refreshed §4.6 still doesn't know: schema version field, guaranteed-vs-catalog-specific keys, empty/no-match message shape, evolution policy when a catalog adds new columns. The success criterion implies forward-compatibility that a single payload example can't deliver. Decide between (a) tighten R1 to require an evolution-policy note in §4.6 (one sentence: "new catalogs may add keys; consumers must treat unknown keys as additive"; name guaranteed vs catalog-specific keys), or (b) weaken Success Criterion 1 to scope it explicitly to the current four-catalog snapshot rather than implying forward-compatibility.
