---
title: "Refresh Service Design Doc to Current DEV Deployment - Plan"
type: docs
date: 2026-07-07
topic: refresh-design-doc-dev-state
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-brainstorm
execution: code
---

# Refresh Service Design Doc to Current DEV Deployment - Plan

**Product Contract preservation:** Product Contract unchanged. The structural open question (home for the ops layer) is resolved in KTD1; the corresponding Outstanding Question is retired.

## Goal Capsule

- **Objective:** Bring `scimma_crossmatch_service_design.md` into agreement with what is actually deployed on the DEV cluster, keeping it as the canonical architecture doc.
- **Product authority:** Scott Koranda (maintainer).
- **Open blockers:** None.

## Product Contract

### Summary

Audit all 11 sections of `scimma_crossmatch_service_design.md` against the running DEV deployment and reconcile them. Correct genuine drift, resolve now-decided TBDs, and add explicit "as deployed on DEV" callouts where DEV's running instantiation diverges from the target design. The doc stays a forward-looking architecture doc; the refresh makes it accurate, it does not rewrite it into an as-built manual.

### Key Decisions

- **Comprehensive audit, not just the deployment delta.** Every section is verified against reality, not only the sections touched by recent deployment work. The core app sections are expected to still match, but they are confirmed rather than assumed.
- **The doc stays the canonical architecture doc.** Design intent remains authoritative. DEV reality is captured through inline "as deployed on DEV" callouts, not by replacing design statements with as-built prose. Prod-target statements survive as design.
- **Three sources of truth, with precedence.** The live DEV cluster (kubectl) and the gitops overlay are authoritative for *deployed* facts; the app-repo code is authoritative for *behavior*.

### Requirements

**Audit method**

- R1. Every one of the doc's 11 sections is reconciled against the deployed DEV state; no section is left current-by-assumption.
- R2. Each checkable claim is verified against the three sources of truth — the live DEV cluster (`kubectl`), the gitops repo (`crossmatch-service-k8s-gitops`: `apps/*/values-dev.yaml`, `argocd-apps/`), and this app repo (code + `deploy-contract.yaml`) — with cluster and gitops authoritative for deployed facts and app code authoritative for behavior.
- R3. Genuine errors are corrected in place; "recommendation"/"suggested"/"initial"/TBD passages that are now decided are resolved to the deployed reality; TBDs that are still genuinely open stay TBD.
- R4. Where DEV's running instantiation diverges from the target design, an explicit "as deployed on DEV" callout is added rather than overwriting the design statement.

**Operator/ops layer to add (currently absent from the doc)**

- R5. Document the operator-surface authentication gate: oauth2-proxy as a CILogon OIDC client, enforced by Traefik forwardAuth, authorizing on a CILogon `sub` roster via a dedicated auth host, protecting the Grafana and Flower surfaces.
- R6. Document the monitoring spine: kube-prometheus-stack (Prometheus, Grafana, Alertmanager, node-exporter, kube-state-metrics) plus the deployed `celery-exporter` and `postgres-exporter`.
- R7. Document the ingress layer: Traefik on k3s (DaemonSet, hostPorts, ClusterIP service, Jetstream2 floating IP), the DEV hostnames (`crossmatch-dev.scimma.org`, `grafana.*`, `auth.*`), cert-manager TLS (Let's Encrypt HTTP-01), and Flower's exposure behind the gate.
- R8. Document the GitOps/ArgoCD deploy model: ArgoCD `Application` objects in `argocd-apps/` applied by hand (no app-of-apps), auto-sync of `apps/` path sources, and SealedSecrets for secret material.

**Confirmed DEV deviations to reconcile**

- R9. Notifier: DEV publishes to an in-cluster plaintext Kafka (`local-kafka`), not Hopskotch; reconcile the notifier section with a DEV callout.
- R10. Task broker/result backend: DEV runs **Redis**, not Valkey; reconcile Section 6 (title and body).
- R11. Database: DEV runs an in-cluster `django-db` PostgreSQL Deployment; reconcile the database section's deployment framing.
- R12. Dask: DEV runs the scheduler and worker inside the cluster (`dask` namespace) via the same gitops repo (`apps/dask`), which diverges from the doc's "separate project / shared infrastructure" description; add a DEV callout.
- R13. Brokers: all three consumers (ANTARES, Lasair, Pitt-Google) are deployed and running on DEV; confirm the doc reflects this rather than treating any as aspirational.
- R14. Deployment specifics: record the current DEV image tag (`0.3.0`), the DEV consumer group ids (`scimma-crossmatch-dev`), and the k3s cluster shape (one control node + two workers) as DEV callouts.

**Consistency**

- R15. After edits, cross-references, section numbers, and the env-var contract catalog stay internally consistent; the deployment section's env-var surface matches the current `deploy-contract.yaml` and the gitops overlay.

### Scope Boundaries

- Documentation only — no code or manifest changes.
- No architecture redesign; prod-target design statements are preserved as design.
- Non-DEV environments (staging/prod) are not documented beyond the existing design intent.
- Still-undecided TBDs (e.g., the notifier -> LSST return mechanism) stay TBD.

### Dependencies / Assumptions

- Access to the live DEV cluster (kubeconfig at `crossmatch-service.kubeconfig`) and a checkout of the gitops repo (`../crossmatch-service-k8s-gitops`) are available.
- Source-of-truth precedence per R2 holds (cluster + gitops for deployed facts, app code for behavior).
- The recent `docs/solutions/` learnings on the ops layer and `CONCEPTS.md` are accurate inputs for the auth/monitoring/ingress sections.

---

## Planning Contract

### Key Technical Decisions

- **KTD1. The net-new ops layer expands the existing Deployment section (§9), it is not a new top-level section.** Add `9.3 Operator Surfaces & Access Control`, `9.4 Monitoring & Observability`, `9.5 Ingress & TLS`, and `9.6 GitOps / ArgoCD Delivery`, with short forward-references from Components (§2) and the Observability line (§8.1). Rationale: these are deployment/infrastructure concerns; localizing them under §9 keeps the ten architecture sections design-focused and consistent with the "design canonical + DEV callouts" framing.
- **KTD2. DEV deviations are inline "as deployed on DEV" callouts, not overwrites.** Redis-not-Valkey (§6), local Kafka (§4.6), in-cluster `django-db` (§5), in-cluster Dask (§7.4), image tag and consumer group ids (§9) are each noted where they occur; the target-design statement stays and the callout records what DEV runs today. Design intent remains authoritative.
- **KTD3. Verification precedence: live cluster + gitops overlay for deployed facts, app-repo code for behavior.** A claim about what is running is checked with `kubectl` and the `values-dev.yaml` / `argocd-apps/` overlay; a claim about how the code behaves is checked against the app source.
- **KTD4. The ops-layer content is sourced from the existing learnings, not re-derived.** `docs/solutions/design-patterns/traefik-forwardauth-central-oauth2-proxy-gate.md`, `docs/solutions/conventions/argocd-apps-applied-manually.md`, `docs/solutions/integration-issues/traefik-hostport-daemonset-rollout-deadlock.md`, `docs/solutions/runtime-errors/oauth2-proxy-cookie-secret-byte-length.md`, and `CONCEPTS.md` are authoritative inputs for §9.3–§9.6.

### Approach

One audited pass per section cluster. U1 assembles a single deployed-DEV fact sheet so later units cite it instead of re-surveying the cluster. U2–U7 reconcile section clusters in document order, each editing `scimma_crossmatch_service_design.md` and each verifying its claims against the U1 fact sheet (and re-checking directly when the fact sheet is silent). U8 is a whole-doc consistency and TBD pass that runs last. The deliverable is the single updated markdown file; there is no code or test change, so per-unit verification is a fact-check against the deployed state and an internal-consistency check, not a test run.

---

## Implementation Units

### U1. Assemble the deployed-DEV ground-truth reference

- **Goal:** Produce one authoritative fact sheet of the current DEV deployment that every later unit cites, so the audit verifies against a single gathered source rather than re-surveying per section.
- **Requirements:** R1, R2.
- **Dependencies:** none.
- **Files:** no change to the design doc; working notes may live in the session scratchpad (not committed).
- **Approach:** Enumerate from the live cluster (`kubectl` across `crossmatch-service`, `monitoring`, `oauth2-proxy`, `dask`, `traefik`, `cert-manager`, `argocd`, `kube-system`): workloads and their images, Services, Ingresses, and the DEV hostnames. Enumerate from the gitops overlay (`crossmatch-service-k8s-gitops`): `apps/*/values-dev.yaml`, `argocd-apps/*.yaml`, and each app's source. Capture the claim classes the doc makes: component inventory, broker consumers, database, task broker/backend, notifier target, Dask topology, catalog roster, image tag, ingress hosts/TLS, auth gate, monitoring stack, and the ArgoCD delivery model.
- **Verification:** The fact sheet covers every claim class above and each entry is attributed to a source (cluster or gitops path).
- **Test expectation:** none — investigation, no behavior change.

### U2. Reconcile the architecture and data-flow sections (§1–§3)

- **Goal:** Verify Goals/Non-Goals (§1), Components (§2.1), Broker Filter Standard (§2.2), and Data Flow / sequence diagram (§3) against the U1 fact sheet; correct drift; confirm all three broker consumers run on DEV; add forward-reference stubs from §2 Components to the new §9.3/§9.4 ops subsections.
- **Requirements:** R1, R3, R4, R13 (forward-refs support R5, R6).
- **Dependencies:** U1.
- **Files:** `scimma_crossmatch_service_design.md` (§1–§3).
- **Approach:** Confirm the component list matches deployed workloads; add an "as deployed on DEV" note where the running set differs from the design's component framing; leave the sequence diagram intact unless the data flow actually diverges.
- **Verification:** Every §1–§3 claim matches the U1 fact sheet or carries a DEV callout; forward-reference stubs to §9.3/§9.4 are added here (their targets are created in U6; stub resolution is confirmed in U8's consistency pass).
- **Test expectation:** none — documentation.

### U3. Reconcile the interfaces and notifier section (§4)

- **Goal:** Verify the broker interfaces (§4.1–§4.4) and notifier (§4.5–§4.6); add the DEV callout that the notifier publishes to in-cluster `local-kafka` (topic `crossmatch-test`, auth disabled via empty credentials) rather than Hopskotch; confirm §4.5 notifier -> LSST stays TBD.
- **Requirements:** R3, R4, R9, R13.
- **Dependencies:** U1.
- **Files:** `scimma_crossmatch_service_design.md` (§4).
- **Approach:** Keep the Hopskotch design description in §4.6; append an "as deployed on DEV" callout for the local-Kafka target. Verify each broker interface's connection details against app code (behavior) and confirm the consumer is running (deployed fact).
- **Verification:** §4.6 carries the local-Kafka DEV callout; §4.5 remains TBD; broker interface details are consistent with app code.
- **Test expectation:** none — documentation.

### U4. Reconcile the database and task-orchestration sections (§5, §6)

- **Goal:** §5 — note the in-cluster `django-db` PostgreSQL Deployment as the DEV database instantiation. §6 — reconcile the "Celery + Valkey" framing with the DEV reality that **Redis** serves as the broker/result backend, as an inline DEV callout (Valkey stays as the design intent per KTD2).
- **Requirements:** R3, R4, R10, R11.
- **Dependencies:** U1.
- **Files:** `scimma_crossmatch_service_design.md` (§5, §6).
- **Approach:** Do not rewrite §6's title away from the design choice; add a callout that DEV currently runs Redis. For §5, add a DEV note on the `django-db` Deployment without redesigning the table/transaction content, which is behavior and stays as-is.
- **Verification:** §6 carries the Redis DEV callout; §5 carries the `django-db` DEV note; neither section's design content is rewritten.
- **Test expectation:** none — documentation.

### U5. Reconcile the LSDB/Dask and Python-implementation sections (§7, §8)

- **Goal:** §7.4 — add a DEV callout that the Dask scheduler and worker run in-cluster (`dask` namespace) via the same gitops repo (`apps/dask`), diverging from the "separate project / shared infrastructure" description. §8 — reconcile runtime/libraries, package layout, and processes with what is deployed, and record the deployed image tag (`0.3.0`); add an Observability forward-reference from §8.1 to the new §9.4.
- **Requirements:** R3, R4, R12, R14 (forward-ref supports R6).
- **Dependencies:** U1.
- **Files:** `scimma_crossmatch_service_design.md` (§7, §8).
- **Approach:** Keep §7's crossmatch design intact; the only DEV divergence is Dask topology. In §8, confirm the library/observability list against the deployed image and add the image-tag/version anchor as a DEV note.
- **Verification:** §7.4 carries the in-cluster-Dask DEV callout; §8 records the deployed image tag and forward-references §9.4.
- **Test expectation:** none — documentation.

### U6. Expand the Deployment section with the deployed ops layer (§9.3–§9.6)

- **Goal:** Add the four ops subsections describing what is deployed: `9.3 Operator Surfaces & Access Control` (oauth2-proxy/CILogon gate, Traefik forwardAuth, `sub` roster, auth host, Grafana + Flower), `9.4 Monitoring & Observability` (kube-prometheus-stack + `celery-exporter` + `postgres-exporter`), `9.5 Ingress & TLS` (Traefik DaemonSet/hostPort/ClusterIP/floating IP, DEV hostnames, cert-manager Let's Encrypt HTTP-01), and `9.6 GitOps / ArgoCD Delivery` (Applications applied by hand / no app-of-apps, `apps/` auto-sync, SealedSecrets).
- **Requirements:** R5, R6, R7, R8.
- **Dependencies:** U1.
- **Files:** `scimma_crossmatch_service_design.md` (§9).
- **Approach:** Draw the content from the KTD4 learnings and `CONCEPTS.md`; describe deployed reality, not aspiration. Use the `CONCEPTS.md` vocabulary (Operator surface, Gate, Auth host, Roster) so the doc and glossary agree.
- **Execution note:** The four `docs/solutions/` ops learnings and `CONCEPTS.md` are the authoritative source for this content; cite them rather than re-deriving the mechanics.
- **Verification:** §9.3–§9.6 exist and each claim (workloads, hostnames, auth model, ArgoCD model) matches the U1 fact sheet; the vocabulary matches `CONCEPTS.md`.
- **Test expectation:** none — documentation.

### U7. Reconcile the core Deployment prose and env-var contract (§9.1, §9.2)

- **Goal:** Reconcile §9.1's gitops/registry/deploy-contract description with the ArgoCD reality (cross-link to §9.6), record the DEV image tag (`0.3.0`), consumer group ids (`scimma-crossmatch-dev`), and the k3s cluster shape (one control node + two workers) as DEV callouts; verify the §9 env-var contract catalog matches `deploy-contract.yaml` and the gitops overlay; confirm §9.2 local-dev Docker Compose is still accurate.
- **Requirements:** R8, R14, R15.
- **Dependencies:** U1, U6.
- **Files:** `scimma_crossmatch_service_design.md` (§9.1, §9.2).
- **Approach:** Keep the registry/deploy-contract design description; add the ArgoCD delivery cross-reference and the DEV-specific anchors. Diff the env-var catalog against `deploy-contract.yaml` and flag any entry that no longer matches.
- **Verification:** §9.1 cross-links §9.6; the env-var catalog matches `deploy-contract.yaml` and the gitops overlay; image tag, group ids, and cluster shape are recorded.
- **Test expectation:** none — documentation.

### U8. Whole-doc consistency and TBD pass (§10 and cross-references)

- **Goal:** Resolve now-decided TBDs/"recommendations" to deployed reality (R3); refresh §10 Open Questions (drop resolved items, keep genuinely open ones); verify all cross-references, section numbers, and the intro/component summaries are internally consistent after the U2–U7 edits.
- **Requirements:** R3, R15.
- **Dependencies:** U2, U3, U4, U5, U6, U7.
- **Files:** `scimma_crossmatch_service_design.md` (§10 and whole-doc).
- **Approach:** Read the doc end to end after the section edits; fix stale cross-references and section numbers introduced by the new §9 subsections; apply the one-pass contradiction test to each section.
- **Verification:** §10 reflects only still-open questions; no dangling or wrong section references; each section passes a single-pass contradiction read.
- **Test expectation:** none — documentation.

---

## Verification Contract

- **VG1. Fidelity.** Every reconciled section's claims match the U1 deployed-DEV fact sheet, or carry an explicit "as deployed on DEV" callout where design and reality differ. Spot-checkable against `kubectl` and the gitops overlay.
- **VG2. Ops layer complete.** §9.3–§9.6 are present and each describes the actually-deployed auth gate, monitoring spine (including the celery and postgres exporters), ingress/TLS, and ArgoCD delivery model.
- **VG3. Deviations captured.** Each confirmed deviation (R9 local Kafka, R10 Redis, R11 `django-db`, R12 in-cluster Dask, R14 image tag / group ids / cluster shape) appears as an inline DEV callout in its section.
- **VG4. Internal consistency.** Cross-references and section numbers resolve; the env-var catalog matches `deploy-contract.yaml`; the doc renders as valid markdown; each section passes a one-pass contradiction read.

## Definition of Done

- U1–U8 complete; all of R1–R15 addressed in the doc or explicitly left as still-open TBD.
- `scimma_crossmatch_service_design.md` agrees with the deployed DEV state per VG1–VG4; design intent preserved with DEV callouts where reality diverges.
- Changes committed on a branch (never `main`), left for the maintainer to push and open as a PR against `upstream`.

---

## Sources & Research

- The doc under refresh: `scimma_crossmatch_service_design.md` (11 sections; deployment lives in §9; heading map confirmed this session).
- Deployed DEV inventory (kubectl, this session): namespaces `argocd`, `cert-manager`, `crossmatch-service`, `dask`, `monitoring`, `oauth2-proxy`, `traefik`; `crossmatch-service` workloads `django-db`, `flower`, `local-kafka`, `redis`, `celery-beat`, `celery-worker` (x2), and the `antares`/`lasair`/`pittgoogle` consumers; `monitoring` includes `celery-exporter` and `postgres-exporter`; `dask` runs `dask-scheduler` + `dask-worker`.
- GitOps overlay: `crossmatch-service-k8s-gitops` (`apps/crossmatch-service/values-dev.yaml`, `apps/monitoring`, `apps/oauth2-proxy`, `apps/dask`, `argocd-apps/`).
- Ops-layer learnings (KTD4): `docs/solutions/design-patterns/traefik-forwardauth-central-oauth2-proxy-gate.md`, `docs/solutions/conventions/argocd-apps-applied-manually.md`, `docs/solutions/integration-issues/traefik-hostport-daemonset-rollout-deadlock.md`, `docs/solutions/runtime-errors/oauth2-proxy-cookie-secret-byte-length.md`; and `CONCEPTS.md`.
- Prior refresh precedent: `docs/plans/2026-06-12-001-refactor-refresh-service-design-doc-plan.md`.
