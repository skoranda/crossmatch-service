---
date: 2026-04-28
topic: dashboard-web-ui
focus: dashboard web UI for operators (monitoring, status, reporting, troubleshooting)
mode: repo-grounded
---

# Ideation: Operator dashboard for the SCiMMA crossmatch service

This ideation covers an operator-only dashboard. Scientist-facing surfaces (filter builders, science exploration, candidate browsing) are explicitly out of scope here — they belong in a separate ideation with their own audience analysis.

## Grounding context

### Codebase context
- Django 6.0+ alert-ingest service. Stack: Celery (workers + beat), Dask cluster, Postgres, Valkey/Redis. Hopskotch publish at the tail.
- Top-level dirs: `crossmatch/` (core), `docker/`, `kubernetes/`, `docs/`. K8s-native via Helm; oauth2-proxy already used in front of Flower in some envs.
- Existing UI/observability surfaces: Django admin (in `INSTALLED_APPS`, undocumented exposure), Flower (running, no K8s ingress documented), Dask Bokeh dashboard (not exposed). No REST API (no DRF). No custom dashboard.
- Domain models: `Alert`, `AlertDelivery` (per-broker), `CatalogMatch` (Gaia/DES/DELVE/SkyMapper), `CrossmatchRun` (queued / running / succeeded / failed), `Notification`.
- Brokers consumed: ANTARES (Kafka), Lasair (Kafka), Pitt-Google (Pub/Sub with server-side SMT JS UDF for reliability ≥ 0.6, replicas:1 pinned because `update_subscription` races).
- Operator pain points: fragmented observability (Flower + admin live in different places); no per-broker drop-rate visibility; SMT UDF code on a live subscription has no in-repo reflection of what's actually attached; Dask version drift triage is manual; no surfaced "why did this alert get dropped"; no incident timeline; no MTTR or capacity reporting; no external-facing status surface for partners.
- Leverage: clean ORM (HTMX-direct viable for low-volume operator views); Celery and Dask both expose Prometheus `/metrics`; oauth2-proxy precedent; Helm chart pattern is well-trodden.

### Past learnings
`docs/solutions/` does not exist. Operator-dashboard work is greenfield from an institutional-knowledge standpoint. Capture decisions via `/ce-compound` after work lands.

### External context (operator-relevant prior art)
- **Rubin LOVE** (Vue + SAL + ArgoCD): observatory control-room dashboard with role-separated views. Time-series live in a sidecar (EFD + Chronograf), keeping ops time-series out of the science store. Direct precedent for splitting ops time-series from the application database.
- **Pitt-Google headless broker** (cautionary): GCP-native (Dataflow + BigQuery + Pub/Sub) with no portal. Operators have zero shared visibility — exactly the failure mode this ideation addresses.

### Adjacent solutions
- **Celery monitoring**: Flower is in-memory only, no retention, single-broker, ~1k tasks/hr ceiling. `grafana/celery-exporter` is the production-grade Prometheus path. Importable Grafana dashboards (IDs 9610, 9970).
- **Dask dashboard embedding**: known WebSocket / CORS / `bokeh<3.0` proxy failures. Recommended: scrape `dask.distributed` `/metrics` from scheduler and render in Grafana, do not iframe Bokeh.
- **Centralized logs**: Grafana Loki sits naturally next to Prometheus + Grafana, single Helm chart, query language (LogQL) similar enough to PromQL to be ops-learnable. Replaces ssh+grep for cross-pod log search.
- **Status pages**: Statuspage.io and Atlassian Statuspage are the SaaS standard; `cstate` and `gatus` are open-source equivalents that publish a static-rendered or live-checked status page from YAML config. Partner-facing.
- **SLOs**: Google SRE Workbook patterns (error budget, burn-rate alerts) are the standard playbook. Prometheus alerting rules + Alertmanager support multi-window multi-burn-rate alerts directly.

### Cross-domain analogies (operator-relevant)
- **Trading desk ops surface**: fast-path widgets, threshold-aware, 10–60s refresh, no ad-hoc queries.
- **Observatory control room (Rubin LOVE)**: separate ops time-series store from the application database.
- **SCADA alarm rationalization**: every displayed metric must be actionable and have a defined normal band. No ornament.
- **NOC L1/L2/L3 escalation**: tier-scoped view depth maps onto Django group permissions.

## Ranked ideas

### 1. Per-alert "why did this go where it went?" trace
**Description:** A search input that takes an `alertId`, `diaSourceId`, or broker message-id and returns a deterministic timeline: ingested at T from broker B, server-filter result (passed / dropped, reason, threshold value), normalize step, queue path, Dask run id and outcome, catalog matches with distances and reliability, delivery + notification outcomes. Same data exposed at `/api/v1/alerts/{id}/trace.json` for scriptable use by on-call and partner-facing support.
**Warrant:** `direct:` Grounding pain: "no surfaced 'why did this alert get dropped'." Repo: `crossmatch/brokers/__init__.py` records only successful deliveries via `AlertDelivery` — no symmetric drop record. `Alert`/`AlertDelivery`/`CatalogMatch`/`CrossmatchRun`/`Notification` are FK-keyed on `Alert`, so the trace is a join.
**Rationale:** This is the operator's most common forensic question — almost always triggered by a partner email asking "where did alert X go?" Today the only path is a Django shell + psql session. A URL-shaped trace replaces ssh+grep with seconds and is shareable in a Slack/email reply.
**Downsides:** Requires schema additions to capture *drop* events the same way deliveries are captured (overlaps with the audit-event substrate the runbook idea also wants). Looks thin until enough event types are emitted.
**Confidence:** 90%
**Complexity:** Medium
**Status:** Unexplored

### 2. Live config-drift reflector page
**Description:** One read-only page that, for each runtime-configurable surface, shows side-by-side: (a) the value the running pod thinks it has (`settings.MIN_DIASOURCE_RELIABILITY`, broker URLs, Dask scheduler address, image tags), (b) the value the live external system reports (Pitt-Google subscription's attached UDF source, ANTARES/Lasair consumer-group + lag, Dask scheduler version, Hopskotch topic), (c) a per-row drift indicator. Optional one-click "reconcile" action gated to operators with audit log.
**Warrant:** `direct:` Grounding pain points: "SMT UDF code on a live subscription has no in-repo reflection of what's actually attached"; "Dask version drift triage is manual." Repo: `_build_reliability_udf(threshold)` in `crossmatch/brokers/pittgoogle/consumer.py` produces deterministic source the page can diff against the live UDF.
**Rationale:** The unique pains of this service aren't "we lack a chart" — they're "we don't know what's running." A drift page is non-substitutable by Grafana, Flower, or any off-the-shelf tool. Highest leverage per LOC of any operator-dashboard idea: every drift bug debugged by hand becomes one more row.
**Downsides:** Cross-cutting reads against several external systems (GCP Pub/Sub, Kafka admin client, Dask scheduler) bring auth + reliability concerns. The reconcile button is a write action with RBAC + audit storage requirements that block design until resolved.
**Confidence:** 90%
**Complexity:** Medium
**Status:** Unexplored

### 3. Self-healing runbook substrate with audit log
**Description:** A small framework where ops chores are Python callables annotated with `@runbook(name, requires_role, idempotency_key)`. Each becomes simultaneously a button on the console, a `manage.py` subcommand, and an authenticated POST endpoint. Every invocation writes to a structured audit-event log. Seed with three known recurring chores: re-attach the Pitt-Google SMT UDF, replay a `CrossmatchRun` in `state=FAILED`, re-publish a `Notification` in `state=FAILED`.
**Warrant:** `direct:` Repo: `CrossmatchRun.state=FAILED` with `attempts` and `last_error` already modelled (`crossmatch/core/models.py`); Pitt-Google SMT re-attach is a single function call with a known race (`update_subscription` races, `replicas: 1` pinned in Helm values). `external:` NOC L1/L2/L3 escalation maps role-scoped runbook buttons onto Django groups.
**Rationale:** Today the response to any in-flight failure is "ssh to a pod and run a Django shell." A substrate turns each new failure mode into a button + audit row. The substrate is the compounding asset — buttons are just instances. Same registry powers later chatops + scheduled remediation + on-call docs that link to a clickable action.
**Downsides:** First write-path on the new dashboard surface; introduces auth / RBAC + audit storage decisions that block until resolved. Risk of becoming a feature-creep target.
**Confidence:** 80%
**Complexity:** Medium-High
**Status:** Unexplored

### 4. Adopt Grafana + celery-exporter + Dask `/metrics` + Loki for the monitoring spine
**Description:** Stand up the production-standard observability stack as a sidecar, behind the same oauth2-proxy used for Flower:
- `grafana/celery-exporter` scraping into Prometheus
- Dask scheduler `/metrics` scraped into Prometheus
- Postgres `pg_exporter`
- Grafana Loki for centralized logs from all pods (consumer, worker, beat, scheduler)
- Grafana for visualization, importing community dashboards (IDs 9610, 9970) as the starting point
Embed selected Grafana panels into the operator console's monitoring tab via signed iframe URLs. Loki provides cross-pod log search by alertId/correlation-id, replacing ssh+grep. Deprecate Flower once the relevant panels are reproduced.
**Warrant:** `direct:` Grounding: Flower is "in-memory only, no retention, single-broker, ~1k tasks/hr ceiling … `celery-exporter` (now under grafana/) is the production-grade Prometheus path … recommended: scrape `dask.distributed` `/metrics` from scheduler and render in Grafana, do not iframe the Bokeh server." Repo: `kubernetes/charts/crossmatch-service/values.yaml` line 76 has `flower:` with `hostname: ""` and a TODO about consolidating with oauth2-proxy. `external:` Rubin LOVE separates ops time-series (EFD + Chronograf) from the science store, validating the sidecar pattern.
**Rationale:** Every hour spent rendering a worker-count gauge or wiring per-pod log shipping is an hour stolen from #1, #2, #3 — the things only this codebase can build. The Grafana + Prometheus + Loki stack also brings retention + alerting + dashboards-as-code for free, all of which the current Flower + admin patchwork lacks. Adopting Loki specifically removes the troubleshooting friction of "ssh into the pod that was running at 14:32 to grep its logs."
**Downsides:** New operational surface to run + auth + maintain (three sidecars: Prometheus, Grafana, Loki). Loki adds storage cost; needs retention policy decisions.
**Confidence:** 85%
**Complexity:** Medium
**Status:** Unexplored

### 5. SLO definitions + Prometheus alerting rules
**Description:** Define explicit SLOs for the service: per-broker connectivity (≥ 99% over 30 days), end-to-end ingest latency (p95 ≤ 60s from broker publish to Hopskotch republish), Dask cluster availability (≥ 99% with ≥ 1 worker), crossmatch success rate (≥ 99% per `CrossmatchRun.state` transitions). Encode them as YAML in `kubernetes/charts/.../slo-rules.yaml` consumed by Prometheus (depends on #4). Configure multi-window multi-burn-rate alerting per the SRE Workbook, routing to PagerDuty (or whatever the team's on-call destination is) for fast burns and Slack for slow burns.
**Warrant:** `external:` Google SRE Workbook on multi-window multi-burn-rate alerting; Prometheus + Alertmanager native support. `reasoned:` Without explicit SLOs, every incident is a judgement call about "was that bad enough to page?" — burnout-driving and inconsistent. SLOs make the page-or-not decision rule-based and visible to the team in advance.
**Rationale:** Forces the team to confront, in advance: what *is* our commitment? An SLO file in the repo is a contract a partner can read and an on-call rotation can train against. The SLO definition exercise itself surfaces missing instrumentation (typically several of the metrics needed don't yet exist) — that's the actual high-leverage work, paid down once and benefiting every later alert.
**Downsides:** SLO definition is a multi-meeting team conversation, not just engineering work. Risk of premature SLOs that are either too loose (no signal) or too tight (alert fatigue) — requires a tuning period.
**Confidence:** 80%
**Complexity:** Medium
**Status:** Unexplored

### 6. External-facing status page
**Description:** A partner-readable URL (e.g., `status.crossmatch.scimma.org`) showing per-broker connectivity (green / yellow / red), current ingest throughput (last 1h), last successful crossmatch run timestamp, time since last published Hopskotch message, and a current-incident banner driven by the runbook substrate's audit log. No auth — public. Renders from a static cache that a Celery beat task refreshes every 30s, so the status page itself can stay up even if the upstream service is degraded.
**Warrant:** `external:` Open-source `gatus` and `cstate` projects are the canonical patterns; Atlassian Statuspage is the SaaS reference for what partners expect. `reasoned:` SCiMMA partners (Lasair, ANTARES, Pitt-Google teams; downstream Hopskotch consumers) currently have no shared signal that this service is healthy — every "are you guys down?" question is an email. A status page collapses the question into a URL.
**Rationale:** Operator visibility ≠ operator solitude. The team is already fielding partner status questions; a status page is the lowest-cost way to absorb that operational surface. Reuses #4's Prometheus signals + #5's SLO rules; doesn't need its own metrics pipeline.
**Downsides:** Public surface = public scrutiny. A status page that's wrong (says green when red) erodes trust faster than no status page. Needs the underlying signals from #4 to be reliable first; should not ship before #4 is in production.
**Confidence:** 70%
**Complexity:** Low-Medium (assuming #4 has shipped)
**Status:** Unexplored

### 7. Weekly ops digest (auto-generated Markdown report)
**Description:** A Celery beat task that runs every Monday morning, queries the audit-event log + Postgres + Prometheus, and produces a Markdown report covering: ingest counts per broker (with week-over-week deltas), drop counts and top reasons, batch wait/size distributions, top errors and their first/last occurrence, capacity trend (Postgres growth, batch backlog age), and any SLO-burn incidents from the week. Posts to a Hopskotch ops topic (or Slack channel), emails the team, and writes a static copy to `/digests/YYYY-Wnn.md` so a year of reports is browsable from a single index page.
**Warrant:** `direct:` Repo: Celery beat is already in `INSTALLED_APPS` (`django_celery_beat`); `crossmatch/tasks/schedule.py` exists; the Hopskotch publisher path is end-to-end (`crossmatch/notifier/impl_hopskotch.py`). `reasoned:` Most operator stakeholders need narrative summaries (papers, weekly stand-ups, leadership reviews), not real-time chrome. A digest is auditable, archivable, forwardable. Reuses existing infra; adds zero new runtime surfaces.
**Rationale:** Cheap reporting layer that pays back every week and compounds — each report is a primary source for incident-history conversations, capacity-planning decisions, and "did anything weird happen this week?" review. Hard to skip once the team is reading it; one of the highest signal-to-build-effort ratios in this set.
**Downsides:** Risk of becoming wallpaper if no one is actually reading the report — needs a designated reader (rotating on-call lead?). Quality of the report depends on the audit-event log existing (overlaps with #1 + #3 substrate).
**Confidence:** 75%
**Complexity:** Low
**Status:** Unexplored

## Cross-cutting compositions

These are not separate ideas; they are coherent ways to combine survivors into a phased plan.

- **Operator console spine — #1 + #2 + #3.** Per-alert trace, drift reflector, and runbook substrate share one engineering investment: a single Django `console` app, a `/api/v1/` REST contract, and a structured audit-event log. Each is independently useful; together they form the asset that compounds. None are substitutable by off-the-shelf tools. The audit-event log seeded by #3 also provides the data for #1's drop events and #7's weekly digest.
- **Monitoring spine — #4 + #5.** Grafana + Prometheus + Loki carries the time-series and log layer; SLO + alerting rules turn raw metrics into commitments and pages. Adopting them in this order (#4 first, then #5) avoids paging on metrics that aren't yet validated.
- **Partner-facing layer — #6 + #7.** Both reuse #4 + #5 signals and the audit log from #3. Status page is real-time; weekly digest is narrative. Together they cover the spectrum of "is it healthy right now?" and "how was the week?" without a custom UI for either.
- **Phasing.** Phase 0: ship #4 (monitoring spine — buys retention, alerting, log search immediately). Phase 1: build #1 + #2 + #3 (operator console spine — domain-specific value). Phase 2: layer #5 + #6 + #7 (commitments + partner-facing surfaces — depend on the prior phases' signals).

## Rejection summary

| # | Idea | Reason rejected |
|---|------|-----------------|
| 1 | Metabase against Postgres read-replica | Out of scope after refocus to operators (was a science-exploration tool). |
| 2 | Saved Filters → Hopskotch republish topics | Out of scope after refocus to operators (was a scientist subscription model). |
| 3 | django-unfold over Django admin (weekend MVP) | Less compelling for operator-only audience — operators have psql + ad-hoc shell; the floor #4 sets is higher leverage. Honorable mention as a 1-day fallback if #4 stalls. |
| 4 | Per-broker delivery funnel widget | Subsumed by #1 + ops time-series in #4. |
| 5 | Auto-PR for SMT UDF drift | Subordinate to #2 (drift reflector); enhancement, not a separate idea. |
| 6 | Dask version-drift triage panel | Subsumed by #2 — the drift reflector covers Dask versions as one row. |
| 7 | Single console app + REST contract (standalone) | Architectural emergent property of #1 + #2 + #3 once they ship. |
| 8 | Broker plugin registry | Premature for 3 brokers; revisit after a 4th broker arrives. |
| 9 | Two-surface architecture (standalone) | Strategic principle; folded into #4 (monitoring) + #1–#3 (forensic/action). |
| 10 | Tier-collapsing role view (single URL) | Operators-only refocus narrows the audience axis — not a relevant trade-off here. |
| 11 | Quiet alarm-rationalized landing page | Design constraint, not a standalone idea — fold into #4's dashboards as they land. |
| 12 | Stuck-batch rescue console | Specific instance of #3 (runbook substrate). |
| 13 | Slack/Hopskotch event feed instead of webpage | Subordinate to #5 (alerting rules); the alert-routing destination is the operator's call. |
| 14 | Single-file Django template, no JS, no DRF | Dominated by either #4 (Grafana panels) or the eventual operator console. |
| 15 | HEALPix sky map as ops/science substrate | Premature; high implementation burden for the operator-only leverage. |
| 16 | ATC strip bay metaphor | Ornamental on top of #1 + #3; no distinct functionality. |
| 17 | ED triage board with acuity scores | Ornamental on top of `CrossmatchRun.attempts`/retry signals already in the model. |
| 18 | Sports-broadcast PGM/ISO split | Variant of two-surface principle; already folded in. |
| 19 | Wall-mounted tournament-clock kiosk | Borderline — largely a kiosk-mode template over #4 + #6. Capture as a deployment variant. |
| 20 | KDS expediter-pass view | Ornamental; covered by #4's queue-depth panels. |
| 21 | LLM-agent-first design | Property of REST + audit log, not a separate idea. |
| 22 | Air-gapped / vendor-everything build posture | Below ambition floor — ops hygiene, not a strategic move. |
| 23 | Append-only event log as sole source of truth | Variant of audit-event substrate; already folded into #1 + #3. |
| 24 | Log search by correlation-id (standalone) | Folded into #4's Loki addition rather than building a custom search UI. |

(Science-side rejections from the prior cast — TOM Toolkit plugin, Jupyter library, NLE timeline + bin + viewer, 10k-user public portal — are out of scope after refocus and are not retained in this table.)
