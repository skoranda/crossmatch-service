---
title: "GitOps ArgoCD Applications in argocd-apps/ are applied by hand (no app-of-apps)"
date: 2026-07-07
category: docs/solutions/conventions/
module: gitops/argocd
problem_type: convention
component: development_workflow
severity: high
applies_when:
  - "Adding a new ArgoCD Application to the gitops repo under argocd-apps/"
  - "Changing an existing Application's spec, including an inline source.helm.valuesObject"
  - "A newly merged app never appears in the cluster, or a synced app ignores a values change"
related_components: [tooling]
tags: [argocd, gitops, app-of-apps, kubernetes, helm, deployment]
---

# GitOps ArgoCD Applications in argocd-apps/ are applied by hand (no app-of-apps)

## Context

The gitops repo has **no app-of-apps / root Application**. The ArgoCD `Application`
objects live in `argocd-apps/*.yaml` and are applied to the cluster by hand
(`kubectl apply -f argocd-apps/<file>`). Each app's `syncPolicy.automated`
(prune + selfHeal) then keeps that app's CHILD resources in sync with its source — but
nothing watches `argocd-apps/` itself. This is easy to forget because most GitOps
setups do use an app-of-apps, so "merge to main" feels like it should be enough.

## Guidance

After merging anything under `argocd-apps/`, run
`kubectl apply -f argocd-apps/<changed-or-new>.yaml` for each new or modified
Application. Apps whose source is a repo `path` under `apps/` (the Helm charts) DO pick
up merged file changes via auto-sync — only the Application objects themselves need the
manual apply.

Watch the doubly-easy-to-miss case: some apps (e.g. traefik, cert-manager,
sealed-secrets) carry their Helm values **inline** in the Application via
`source.helm.valuesObject`. Changing those values is an Application-object change, not
an `apps/` change, so it needs the manual `kubectl apply` even though it looks like an
ordinary values edit.

## Why This Matters

Forgetting the manual apply produces silent, confusing failures:

- A newly added app (e.g. `oauth2-proxy`) never appears in
  `kubectl -n argocd get applications`, and nothing deploys — with no error anywhere.
- A changed Application spec does NOT take effect; ArgoCD still shows the app `Synced`
  because it is faithfully syncing its OLD (cluster-resident) spec. In our incident,
  the Traefik app's `allowCrossNamespace` addition was merged but never applied, so the
  oauth2-proxy gate's cross-namespace middleware kept failing and the surfaces 500'd —
  while everything looked green.

## When to Apply

Every time you touch `argocd-apps/`. Make `kubectl apply -f argocd-apps/<file>` the
reflexive next step after the merge, for each Application you added or changed.

## Examples

```bash
# after merging an argocd-apps/ change to gitops main:
kubectl apply -f argocd-apps/oauth2-proxy-dev.yaml     # new Application -> now ArgoCD tracks it
kubectl apply -f argocd-apps/traefik.yaml              # changed inline valuesObject -> spec now live
kubectl -n argocd get applications                     # confirm presence + Synced/Healthy
```

Symptom of the changed-but-not-applied case, from Traefik logs:
`error while reading error page middleware ... service oauth2-proxy/oauth2-proxy is not
in the parent resource namespace <ns>` — the fix was applying the Traefik Application so
its already-merged `allowCrossNamespace` value went live (which then surfaced a separate
[rollout deadlock](../integration-issues/traefik-hostport-daemonset-rollout-deadlock.md)).

Related:
[central oauth2-proxy gate](../design-patterns/traefik-forwardauth-central-oauth2-proxy-gate.md).
