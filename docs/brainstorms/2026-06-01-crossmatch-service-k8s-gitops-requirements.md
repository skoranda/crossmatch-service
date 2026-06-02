---
date: 2026-06-01
topic: crossmatch-service-k8s-gitops
---

# Crossmatch-Service Kubernetes GitOps (DEV)

## Summary

Create a new `crossmatch-service-k8s-gitops` repository, modeled on the existing
`astrodash-k8s-gitops`, that deploys crossmatch-service to the existing
Jetstream2 **DEV** cluster via ArgoCD. The service's existing Helm chart moves
out of the application repo and into the gitops repo as the single source of
truth, adapted from its AWS-EKS origins to Jetstream2, with ingress + TLS as a
first-class capability for the monitoring tools and REST APIs planned next.
Scope is DEV-only, structured so test and prod slot in later without a
restructure.

---

## Problem Frame

crossmatch-service already carries a Helm chart at
`kubernetes/charts/crossmatch-service/`, but it is not a clean deployment
artifact. Its lineage (see the origin brainstorms in Sources) is: scaffolded
production-first (CloudNativePG, SealedSecrets, HA Valkey, node affinity), then
deliberately stripped down to run on a small **dev EKS** cluster — SealedSecrets
removed in favor of `kubectl create secret`, CloudNativePG replaced with a plain
`postgres` Deployment on `emptyDir`, single Valkey, affinity removed. As a
result the chart now carries AWS assumptions (ECR registry, `gp2` storage) and a
manual-secret flow, none of which fit Jetstream2.

The target operating model is the one astrodash already uses: a separate gitops
repository so a developer without Kubernetes experience can run the service
locally with Docker Compose and never open a manifest, while ArgoCD reconciles
the cluster from git. The known cost of separating repos is configuration drift
between the application and its deployment manifests — and that drift has already
bitten this project once (the `2026-03-16-helm-chart-env-gaps` brainstorm
records env vars that existed in `docker-compose.yaml` but were never wired into
the chart). That drift happened inside a single repo, so repo layout is not the
right lever for it; a config contract is. This effort adopts the split **and**
adds a guardrail so the separation does not reintroduce drift.

---

## Key Decisions

- **Split repo over monorepo.** The chart, values, ArgoCD Applications, and
  sealed secrets live in `crossmatch-service-k8s-gitops`; the application repo
  keeps only local-dev tooling. This gives non-Kubernetes developers a
  compose-only local story and isolates cluster/secret concerns from application
  contributors, at the cost of cross-repo coordination — mitigated by the drift
  guardrail below.

- **Relocate the existing chart as the single source of truth, not author
  fresh.** The current chart already encodes the real service architecture
  (three broker consumers, celery worker + beat, valkey, postgres, flower). It
  moves into the gitops repo and is adapted in place; it is removed from the
  application repo so there is exactly one chart. This reuses working wiring
  rather than re-deriving it in astrodash's deployment idiom.

- **SealedSecrets over plain `kubectl` secrets.** Secrets are committed to git
  encrypted (Bitnami SealedSecrets), matching astrodash and keeping the GitOps
  model pure, at the cost of bootstrapping the sealed-secrets controller.

- **GitLab Container Registry + long-lived pull secret.** Images move off AWS
  ECR (whose ~12h token expiry is painful off-AWS) to the GitLab registry,
  pulled with a long-lived GitLab deploy-token credential stored as a committed
  `dockerconfigjson` SealedSecret — exactly astrodash's `gitlab-registry`
  pattern.

- **Persistent Postgres on Cinder.** Postgres moves from the current ephemeral
  `emptyDir` to a persistent Cinder PVC so DEV data survives pod restarts.

- **DEV-only now, with a future-environment seam.** Config splits into shared
  `values.yaml` + `values-dev.yaml` so `values-test.yaml` / `values-prod.yaml`
  can be added later without restructuring. test and prod clusters are operated
  by another team with devops not yet defined, and are out of scope here.

- **Tier-2 drift guardrail.** A single env-var contract in the application repo,
  consumed by a render-diff check in the gitops repo CI. See Requirements
  group "Config-drift guardrail."

---

## Requirements

**Repository structure and split**

- R1. A new repository and top-level directory named `crossmatch-service-k8s-gitops`
  follows the `astrodash-k8s-gitops` layout: `apps/<service>/` (Helm chart),
  `argocd-apps/` (ArgoCD Application CRDs), `infrastructure/`, and `docs/`.
- R2. The Helm chart is relocated from the application repo
  (`kubernetes/charts/crossmatch-service/`) into the gitops repo at
  `apps/crossmatch-service/` and becomes the single source of truth. The
  application repo's `kubernetes/` deployment scaffolding (chart, overrides,
  seal scripts) is removed once relocation is complete and after confirming the
  team that operates the test and prod clusters does not currently deploy from it
  (see Outstanding Questions).
- R3. The application repo retains only local-dev tooling
  (`docker/docker-compose.yaml` and its env files). A developer can run the
  service locally with Docker Compose alone and never edits Kubernetes
  manifests.
- R4. Chart configuration splits into a shared `values.yaml` plus a
  `values-dev.yaml` overlay, structured so `values-test.yaml` and
  `values-prod.yaml` can be added later without restructuring.

**Infrastructure bootstrap (ArgoCD-only cluster)**

- R5. The repo defines ArgoCD Applications under `argocd-apps/` to bootstrap the
  cluster infrastructure that is not yet present: the sealed-secrets controller,
  Traefik ingress controller, and cert-manager. ArgoCD itself is already
  installed on the DEV cluster and is not managed by this repo.
- R6. A bootstrap document captures the order of operations to bring a fresh DEV
  deployment up: register the repo with ArgoCD, apply the infrastructure
  Applications, export and back up the sealed-secrets controller's private key to
  a separate secret store, seal and commit secrets, then apply the application
  Application. The document notes that re-sealing is required if the controller
  key is ever rotated or the controller is reinstalled, since committed
  SealedSecrets are otherwise unrecoverable once plaintext originals are removed.
- R7. cert-manager issues TLS via a Let's Encrypt production ClusterIssuer, and
  Traefik is the ingress class — matching astrodash's infrastructure choices.
  Traefik enforces an HTTP→HTTPS redirect so port 80 serves only the ACME
  challenge and redirects all other traffic to HTTPS.

**Application chart adaptation (EKS to Jetstream2)**

- R8. Image references move from AWS ECR to the GitLab Container Registry. Pulls
  use a long-lived GitLab deploy-token credential stored as a committed
  `kubernetes.io/dockerconfigjson` SealedSecret, mirroring astrodash's
  `gitlab-registry` secret. The deploy token is scoped to `read_registry` only,
  and its expiry and rotation procedure (re-seal a new SealedSecret, then revoke
  the old token in GitLab) are documented in the bootstrap doc.
- R9. Persistent storage uses the Jetstream2 Cinder storage class, replacing the
  EKS `gp2` references.
- R10. Postgres runs with a persistent Cinder PVC, replacing the current
  ephemeral `emptyDir`, so DEV data survives pod restarts.
- R11. All workloads from the existing chart carry over with no change to their
  container spec or run commands — antares / lasair / pittgoogle consumers,
  celery worker and beat, the valkey subchart, postgres, and flower — except
  Postgres storage, which changes to a persistent Cinder PVC per R10. (See
  Deferred / Open Questions on whether flower needs a chart workload authored.)
- R12. Ingress + TLS is a first-class, values-gated capability of the chart,
  ready to expose the planned monitoring dashboards and REST APIs. flower is the
  likely first consumer of this path. Until an authentication layer (oauth2-proxy
  or equivalent) is in front of a service, its ingress defaults to an
  IP-allowlist / network-policy restriction (e.g. the SCiMMA / NCSA CIDR) so no
  surface is ever publicly reachable unauthenticated; the allowlist relaxes once
  auth lands.

**Secrets**

- R13. Secrets are managed as Bitnami SealedSecrets committed to git, replacing
  the application repo's `kubectl create secret` flow. The existing secret
  consumers — `django`, `database`, `antares`, `hopskotch`, and `gcp-pittgoogle`
  — are migrated to SealedSecret resources, conditionally rendered per
  environment as astrodash does.
- R14. A documented `kubeseal`-based secret-sealing workflow exists in the gitops
  repo. The application repo's `kubernetes/scripts/secret_generator/seal_secrets.py`
  is reconciled with it — relocated into the gitops repo or superseded by the
  documented workflow. The workflow specifies a secret-ingestion procedure:
  plaintext values are sourced from a password manager / secret store (never from
  files in the application repo such as `dev-overrides.yaml`), `kubeseal` is run
  locally rather than in CI, and the resulting SealedSecret YAML is the only
  artifact committed. The GCP `key.json` file-secret follows the same local-seal
  procedure.

**Config-drift guardrail (Tier 2)**

- R15. A machine-readable env-var contract lives in the application repo,
  declaring every env var the service consumes, each tagged secret-or-plain and
  by consuming component. It is the consumer's spec, derived from the full
  consumer surface — `crossmatch/project/settings.py` plus the entrypoint scripts
  under `crossmatch/entrypoints/` and any management-command / Celery config that
  reads env. Entrypoint-only vars (`FLOWER_LOG_LEVEL`, `FLOWER_PORT`,
  `FLOWER_URL_PREFIX`, `CELERY_LOG_LEVEL`, `CELERY_CONCURRENCY`, `MAKE_MIGRATIONS`,
  `DEV_MODE`) are in scope for the contract, not just the settings.py surface.
- R16. The gitops repo CI renders the chart (`helm template` with
  `values-dev.yaml`), extracts the env keys delivered to each workload, and fails
  the build if any required plain var is undelivered or any required secret has
  no corresponding SealedSecret. The check is bidirectional: it also fails if a
  var tagged secret in the contract is delivered via a plain `value:` field rather
  than a `secretKeyRef:`, preventing accidental secret demotion to plaintext. CI
  consumes the contract from the application repo at a pinned ref so a contract
  change is a visible, reviewed event.
- R17. During chart adaptation (R8–R12), resolve the known env-var name
  mismatches between consumer and chart so the DEV deployment does not fail on
  missing or empty vars: the app reads `DJANGO_SECRET_KEY` while the chart emits
  `SECRET_KEY`; the app reads `CELERY_TASK_TIME_LIMIT` /
  `CELERY_TASK_SOFT_TIME_LIMIT` while the chart emits `TASK_TIME_LIMIT` /
  `TASK_SOFT_TIME_LIMIT`. This resolution is required regardless of whether the
  contract and CI guardrail (R15/R16) are built; the contract then enforces it
  going forward.

**ArgoCD deployment**

- R18. A `crossmatch-service-dev` ArgoCD Application targets the DEV cluster at
  the `apps/crossmatch-service` path, layering `values.yaml` + `values-dev.yaml`,
  with automated sync, prune, self-heal, and `CreateNamespace=true` — matching
  astrodash's Application shape.

---

## Acceptance Examples

- AE1. **Covers R16.** Given the env-var contract requires a plain var `FOO`,
  when the chart's rendered output for `values-dev.yaml` does not deliver `FOO`
  to the workload that needs it, then the gitops CI render-diff check fails with
  the missing key named.
- AE2. **Covers R16, R13.** Given the contract marks `HOPSKOTCH_PASSWORD` as a
  secret, when no `hopskotch` SealedSecret provides that key, then the check
  fails rather than rendering a workload that would crash-loop on a missing
  secret.
- AE3. **Covers R10.** Given Postgres is running on a Cinder PVC, when the
  Postgres pod is deleted and rescheduled, then previously ingested DEV data is
  still present.
- AE4. **Covers R18, R11.** Given the `crossmatch-service-dev` ArgoCD Application
  is applied, when ArgoCD syncs, then all workloads (antares / lasair / pittgoogle
  consumers, celery worker and beat, valkey, postgres) reach Running and flower is
  reachable over ingress with a valid TLS certificate.

---

## Scope Boundaries

**Deferred for later**

- test and prod clusters and their value overlays — operated by another team
  with devops not yet defined.
- The monitoring dashboards and REST API surfaces themselves, and authentication
  in front of exposed services (e.g. oauth2-proxy). The ingress + TLS path is
  wired; the surfaces behind it land later, and per R12 stay IP-allowlist-gated
  until auth is in place.
- Automated image-tag promotion (e.g. Argo Image Updater). DEV tag bumps are a
  manual edit to `values-dev.yaml` for now.
- A codegen ("Tier 3") guardrail that generates compose env files and chart env
  keys from one source — overkill for a DEV-only service today.
- The optional application-repo compose-vs-contract check (the gitops render
  check is the priority half of the guardrail).

**Outside this effort**

- The remote Dask cluster the service connects to — an external dependency
  reached via Kubernetes service discovery, not deployed by this repo.
- Building the application container image and any application-side CI. The
  gitops repo is pull-only, consuming a pre-built image, as astrodash is.

---

## Dependencies / Assumptions

- The DEV Jetstream2 cluster exists with ArgoCD already installed; the
  sealed-secrets controller, Traefik, and cert-manager are not yet present.
- A Cinder storage class is available on the cluster for the Postgres PVC.
- The service connects to an externally operated remote Dask scheduler via
  Kubernetes service discovery; that scheduler's availability is assumed.
- A GitLab project and Container Registry are available under the relevant SCiMMA
  / `ncsa-caps-rse` organization, with a deploy token usable for image pulls.
- DNS for a DEV hostname can be pointed at the cluster so cert-manager can issue
  Let's Encrypt certificates over HTTP-01.

---

## Outstanding Questions

**Resolve before planning**

- The exact DEV hostname(s) for ingress/TLS, and which service is exposed first
  (likely flower).
- The GitLab project path / namespace for the new repo and the registry image
  location.
- Confirmation that the team operating the test and prod clusters does not deploy
  from the application-repo chart before it is deleted under R2.
- The Dask scheduler's Service name / namespace on Jetstream2 DEV and how
  `DASK_SCHEDULER_ADDRESS` (or the `HOPDEVEL_*_SERVICE_HOST` discovery vars) is
  populated there — the celery worker fail-fasts after a 300s timeout if the
  scheduler is unreachable.

**Deferred to planning**

- Whether `seal_secrets.py` is relocated into the gitops repo or replaced by a
  documented `kubeseal` workflow.
- The Cinder storage class name and PVC sizes for Postgres (and valkey, if
  persisted).
- The application namespace name on the DEV cluster.
- Whether the optional application-repo compose check is built in this pass.

---

## Sources / Research

- `astrodash-k8s-gitops` repository — reference layout, `argocd-apps/` infra
  Applications, `apps/astrodash/` chart, and the `sealedsecret-*` / GitLab
  `gitlab-registry` patterns this effort mirrors.
- Existing chart: `kubernetes/charts/crossmatch-service/` (Chart, values,
  `_helpers.yaml` env blocks, `statefulset.yaml`, `database.yaml`).
- Service component inventory: `docker/docker-compose.yaml`.
- Origin brainstorms explaining the current chart's state:
  `docs/brainstorms/2026-03-16-helm-chart-env-gaps-and-k8s-deployment-brainstorm.md`,
  `docs/brainstorms/2026-03-18-simplify-helm-chart-for-dev-eks-brainstorm.md`,
  `docs/brainstorms/2026-03-16-ghcr-container-registry-brainstorm.md`.
- Consumer env-var surface: `crossmatch/project/settings.py`.

---

## Deferred / Open Questions

### From 2026-06-01 review

Surfaced by document review and deferred for resolution during planning.

- Flower has no chart workload today (only an unused `flower.env` helper define),
  yet R11 lists it among carried-over workloads and R12 names it the first
  ingress consumer. Decide whether to author a flower Deployment / Service for
  DEV or defer flower with the other monitoring surfaces.
- `MIN_DIASOURCE_RELIABILITY` is read at settings import by every consumer, but
  the chart injects `broker_filter.env` only into the pittgoogle consumer, so
  antares / lasair silently fall back to the baked default instead of a
  configured threshold. Decide whether to deliver the var to all consumers or
  make it explicitly optional.
- Is the crossmatch DEV cluster the same Jetstream2 cluster as astrodash-dev, or
  a separate one? This determines whether the R5/R7 infra-bootstrap requirements
  are correct, redundant, or in conflict with controllers already present.
- When a second SCiMMA service deploys to the same cluster, who owns the
  cluster-singleton infrastructure (sealed-secrets, Traefik, cert-manager, the
  default IngressClass, the Let's Encrypt ClusterIssuer) — each service's gitops
  repo with prune / self-heal, or a shared bootstrap repo?
