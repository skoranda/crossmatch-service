---
date: 2026-06-30
topic: monitoring-spine
---

# Monitoring spine for the SCiMMA crossmatch service

## Summary

Stand up a self-hosted monitoring spine on the DEV cluster: the `kube-prometheus-stack`
chart (Prometheus + Alertmanager + Grafana + node-exporter + kube-state-metrics) with
`celery-exporter`, `pg_exporter`, and the Dask scheduler added as scrape targets, wired to
symptom alerts on the failures that have already bitten us. The app is instrumented with
`prometheus_client` for golden-signal dashboards. Grafana is served behind the existing
IPAllowlisted Traefik ingress as a new ArgoCD app. Centralized logs (Loki) and formal SLOs
are explicit later increments.

## Problem Frame

The service now runs on a DEV k3s cluster on Jetstream2, but its only observability surfaces
are Flower (in-memory, no retention), the Django admin, and ad-hoc `kubectl`. Two recent
incidents went undetected until manual triage: the `django-db` PVC filled to 100% and
crash-looped Postgres, and control-plane DiskPressure repeatedly evicted pods (documented in the
GitOps repo's
`docs/solutions/performance-issues/control-plane-diskpressure-undersized-cinder-boot-volume.md`).
In both cases the signal existed — disk usage, pod restarts — but nothing was watching it. The
cost is reactive firefighting: problems surface as partner emails or crash loops. This increment
stands up the metrics, dashboards, and alert rules and makes those signals visible in the
monitoring UI, collapsing triage from an ad-hoc `kubectl` hunt to a glance. It does not yet
deliver proactive alerts with lead time — that needs a live alert channel, which is the explicit
next increment (this increment ships a stubbed receiver, R14). The value here is retained history,
dashboards, and triage speed; delivered lead-time alerting builds directly on top of it.

## Key Decisions

- **Metrics and alerting first; Loki deferred.** Centralized logs are the heaviest disk
  consumer, and the cluster's constraint is disk. Ship the time-series and alerting layer now;
  add logs as a later increment once the footprint is proven.
- **Instrument the app now, but no formal SLOs yet.** Build the golden-signal metrics so real
  dashboards exist, but defer SLO targets and burn-rate alerting until there is baseline data to
  set sane numbers. Day-one SLOs on a fresh DEV cluster would be guesses.
- **`kube-prometheus-stack` over hand-rolled components.** The Operator-based chart is the
  ecosystem standard, ArgoCD-native, and easy to extend per target — worth its modest overhead
  over hand-written scrape configs, tuned down for the small cluster.
- **Self-footprint discipline.** The stack must not recreate the problem it watches: all
  components except node-exporter schedule onto worker nodes with bounded Prometheus retention.
  node-exporter is the deliberate exception (see R17).
- **Stubbed alert receiver for DEV; detection is triage-only this increment.** Alertmanager and the
  rules ship now with a documented stub receiver — alerts are visible in-UI, not delivered. This
  increment therefore improves triage speed, not detection lead time; wiring a live channel to
  convert it into proactive alerting is a config-only change and is the explicit next increment.
- **Grafana inherits the pre-auth posture.** No oauth2-proxy yet, so Grafana sits behind the
  same Traefik IPAllowList gate as Flower rather than blocking on SSO.

## Requirements

**Stack and deployment**

- R1. Deploy the monitoring stack to the DEV cluster as a new ArgoCD `Application`, following
  the existing pattern in the GitOps repo `crossmatch-service-k8s-gitops` (manifest in
  `argocd-apps/`, values under `apps/`, automated sync with `CreateNamespace`).
- R2. Use the `kube-prometheus-stack` community chart, pinned to a specific chart version, with
  bundled components that are not needed disabled.
- R3. Run the stack in its own namespace (e.g. `monitoring`).

**Metrics targets**

- R4. Scrape node-exporter and kube-state-metrics for node and cluster-object health.
- R5. Add Celery metrics via `grafana/celery-exporter` reading the Celery broker (no app *code*
  change; task-outcome metrics require Celery task events, which are off by default — verify and
  enable them, e.g. via remote `enable_events` as the deployed Flower already does. Queue-length
  metrics read the broker directly and are unaffected). Verify the exporter reports non-empty task
  metrics, not just a healthy scrape target.
- R6. Scrape the Dask scheduler's Prometheus `/metrics` endpoint.
- R7. Add Postgres metrics via a `pg_exporter` against the `django-db` instance.
- R8. Provide Grafana dashboards for these targets, seeding from community dashboards (e.g.
  Celery dashboards 9610 / 9970) where they fit.

**App instrumentation (this repo)**

- R9. Instrument the app with `prometheus_client` (already a dependency) to expose a `/metrics`
  endpoint per long-running process (broker consumers, Celery workers, beat).
- R10. Emit golden-signal custom metrics: per-broker ingest counts, an ingest heartbeat /
  last-success timestamp, and crossmatch / notification outcome counters. (Exact metric set
  resolved at planning.)
- R11. Prometheus scrapes the app `/metrics` endpoints.

**Alerting**

- R12. Deploy Alertmanager with rules covering the incident classes that have occurred or are
  high-risk: node disk usage including the control-plane root filesystem; `django-db` PVC
  near-full; Postgres pod down or CrashLooping; pod evictions / `CrashLoopBackOff`; Dask worker
  count below 1; broker-consumer pod liveness; Celery queue backlog growth.
- R13. Alert thresholds and Prometheus retention are values-configurable with sane defaults.
- R14. Alertmanager ships with a stubbed receiver and no live destination; alerts are visible in
  the Alertmanager / Grafana UI. Wiring a real channel is a later config-only change.

**Access**

- R15. Expose Grafana via the existing Traefik ingress + cert-manager + IPAllowList pattern,
  gated to the same source ranges as Flower. Prometheus and Alertmanager UIs are not publicly
  exposed (in-cluster / port-forward only).

**Footprint and scheduling**

- R16. Every stack component except node-exporter schedules onto worker nodes and none run on the
  control-plane. Because Helm cannot share a named template across charts, the anti-control-plane
  affinity + topology-spread blocks must be re-authored in the monitoring app's values per
  kube-prometheus-stack subcomponent (Prometheus, Alertmanager, Grafana, the Operator,
  kube-state-metrics, and each added exporter each expose their own affinity/tolerations keys) —
  not `include`-d from the `crossmatch-service.scheduling` helper. A missed subcomponent silently
  lands on the control-plane.
- R17. node-exporter runs as a DaemonSet on all nodes including the control-plane (with the
  control-plane toleration) so it can observe the control-plane root filesystem — the guardrail
  called for in the DiskPressure solution doc.
- R18. Prometheus retention and PVC size carry conservative defaults so the stack cannot itself
  cause DiskPressure; the Prometheus PVC schedules on a worker.

**Security and credentials**

- R19. Grafana admin credentials are provisioned via a SealedSecret with a non-default password
  before the ingress is activated; the chart's default credentials (`admin`/`prom-operator`) must
  not remain in a deployed state. The IPAllowList gates the network perimeter but is not a
  substitute for application-layer authentication.
- R20. `pg_exporter` authenticates to `django-db` using a dedicated read-only monitoring role with
  minimal privilege; its credentials are stored as a SealedSecret and never appear in values files
  or git history.

## Acceptance Examples

- AE1. **Covers R12, R17.** **Given** node-exporter is running on the control-plane and the
  control-plane root filesystem crosses the configured disk threshold, **then** a disk alert
  fires and is visible in the Alertmanager UI.
- AE2. **Covers R16.** **Given** the stack is synced, **then** Prometheus, Grafana, and
  Alertmanager pods are scheduled on worker nodes and never on the control-plane.
- AE3. **Covers R14.** **Given** an alert fires while the receiver is the stub, **then** it
  appears in the UI, nothing is sent to an external destination, and no delivery error is raised.
- AE4. **Covers R5, R6, R7.** **Given** the stack is synced, **then** the Celery, Dask, and
  Postgres exporters each show as `up` in the Prometheus targets list.
- AE5. **Covers R9, R10, R11.** **Given** a broker consumer is running, **then** a GET on its
  `/metrics` endpoint returns the golden-signal series (a per-broker ingest counter and an
  ingest last-success timestamp gauge), and **then** Prometheus lists that endpoint as `up` and the
  series are queryable.

## Scope Boundaries

Deferred for later (not in this increment):

- Centralized logs (Loki / log aggregation) — the next observability increment.
- Formal SLO definitions and multi-window multi-burn-rate alerting — after baseline data and the
  app instrumentation from R9–R10 exist.
- A live alert destination (Slack, email, PagerDuty) — the receiver stays a stub for DEV; wiring a
  live channel is the explicit next increment (converts triage-only into proactive lead-time alerts).
- oauth2-proxy / SSO in front of Grafana — pending project-wide; IPAllowList is the interim gate.
- The operator-console ideas (per-alert trace, drift reflector, runbook substrate), the public
  status page, and the weekly ops digest — later phases in the source ideation.
- Production deployment — DEV only for this increment.

## Dependencies / Assumptions

- The ArgoCD app pattern, Traefik ingress, cert-manager, and the IPAllowList middleware are
  already in place and reusable (verified in the grounding scan).
- `prometheus-client==0.25.0` is already pinned in the app image but no instrumentation exists
  yet (verified: no `Counter`/`Gauge`/`Histogram`/`start_http_server` in the code) — R9–R10 are
  greenfield.
- The anti-control-plane affinity + topology-spread *pattern* is established, but its Helm helper
  (`crossmatch-service.scheduling`) is not shareable into the external kube-prometheus-stack chart —
  it must be re-authored per subcomponent in the monitoring app's values, exactly as the valkey
  subchart already does (it "has no `_helpers` access," so the same anti-affinity is supplied via its
  own values). See R16.
- The control-plane root volume was extended to ~100 GiB after the DiskPressure incident; the
  control-plane disk alert (R12/R17) remains valuable as an early-warning guardrail.
- Assumption to verify at planning: the Dask scheduler exposes Prometheus `/metrics` natively on
  its dashboard port (the image bakes `dask[complete]`).
- Assumption to verify at planning: `grafana/celery-exporter` can read the DEV Celery broker
  (Valkey/Redis).

## Outstanding Questions

Deferred to planning:

- The `prometheus_client` exposure approach for prefork Celery workers (multiprocess mode vs. a
  dedicated metrics-only process) — a known hard problem that R9/R11 depend on; resolve early, as it
  drives the sizing of the app-instrumentation work.
- Exact custom metric set for R10 (names, types, labels), building on the golden signals R10
  already names, and how the consumers and beat expose `/metrics`.
- Prometheus retention default and PVC size (R18), and the chart version pin plus which bundled
  subcomponents to disable (R2).
- Grafana hostname, and whether to reuse the `crossmatch-service` `allowlistSourceRanges` value
  or duplicate it in the monitoring app's values (R15).
- Whether `pg_exporter` runs as a sidecar on the `django-db` pod or as a standalone Deployment (R7).

## Sources / Research

- Source ideation (#4 monitoring spine, #5 SLOs, phasing):
  `docs/ideation/2026-04-28-dashboard-web-ui-ideation.md`.
- Incident that motivates the control-plane disk guardrail: the GitOps repo's
  `docs/solutions/performance-issues/control-plane-diskpressure-undersized-cinder-boot-volume.md`
  (the guardrail is also R9 in this repo's `docs/brainstorms/2026-06-30-alert-payload-retention-requirements.md`).
- Grounding dossier for this brainstorm:
  `/tmp/compound-engineering/ce-brainstorm/mon-spine/grounding.md`.
