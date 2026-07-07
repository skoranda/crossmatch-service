---
title: "Traefik hostPort DaemonSet rollout deadlocks on the chart-default updateStrategy"
date: 2026-07-07
category: docs/solutions/integration-issues/
module: kubernetes/traefik
problem_type: integration_issue
component: tooling
severity: high
symptoms:
  - "kubectl rollout status ds/traefik times out at '0 out of N new pods have been updated'"
  - "A new traefik pod is stuck Pending; describe shows 'didn't have free ports for the requested pod ports' plus NodeAffinity mismatches on the other nodes"
  - "The running Traefik pods keep the OLD args, so a synced config change never takes effect"
root_cause: config_error
resolution_type: config_change
related_components: [development_workflow]
tags: [traefik, daemonset, hostport, rolling-update, kubernetes, argocd]
---

# Traefik hostPort DaemonSet rollout deadlocks on the chart-default updateStrategy

## Problem

Any change to the Traefik DaemonSet pod template triggers a rolling update that
never completes: the new pod cannot be scheduled and the old pods keep serving the
previous config indefinitely.

## Symptoms

- `kubectl rollout status ds/traefik` hangs, then times out at `0 out of N new pods have been updated`.
- The new pod is `Pending`. `kubectl -n traefik describe pod <new>` shows:
  `0/3 nodes are available: 1 node(s) didn't have free ports for the requested pod ports, 2 node(s) didn't satisfy plugin(s) [NodeAffinity]`.
- The still-`Running` pods carry the OLD args. The config change is present in the
  DaemonSet spec (ArgoCD shows the app `Synced`) but is not live in any pod. In our
  case the change was `--providers.kubernetesCRD.allowCrossNamespace=true`.

## What Didn't Work

- Waiting for the rollout to self-heal — it never progresses.
- `kubectl rollout restart ds/traefik` — same strategy, same deadlock.

The Traefik Helm chart's default DaemonSet `updateStrategy` is `RollingUpdate` with
`maxSurge: 1, maxUnavailable: 0`. With `maxSurge`, the controller creates the NEW
(surge) pod before removing the old one. But Traefik binds host ports 80/443, and only
one pod per node can hold a hostPort. The surge pod is pinned by the DaemonSet's node
affinity to the node whose old pod still owns 80/443, so it can never schedule
("didn't have free ports"), and `maxUnavailable: 0` forbids deleting the old pod
first. Deadlock.

## Solution

Set a hostPort-safe update strategy in the Traefik chart values (top-level
`updateStrategy`), so the DaemonSet deletes-then-recreates one pod per node instead of
surging:

```yaml
# argocd-apps/traefik.yaml  (spec.source.helm.valuesObject)
updateStrategy:
  type: RollingUpdate
  rollingUpdate:
    maxUnavailable: 1
    maxSurge: 0
```

To clear an already-wedged rollout, cycle the old pods so each node's replacement can
bind the freed hostPort (if the surfaces are already down, the per-node blip is free):

```bash
kubectl -n traefik delete pod <stuck-Pending-surge-pod>    # remove the wedged surge pod
for p in <old-pod-node-1> <old-pod-node-2> <old-pod-node-3>; do
  kubectl -n traefik delete pod "$p"        # DaemonSet recreates with the new template
done
kubectl -n traefik rollout status ds/traefik
```

## Why This Works

A hostPort DaemonSet can have only one pod per node bound to the port at a time.
`maxSurge: 0 / maxUnavailable: 1` frees the port (delete old) BEFORE the replacement
needs it (create new), so there is never a two-pods-one-port conflict. `maxSurge >= 1`
inverts that order and deadlocks the moment a hostPort is involved.

## Prevention

- For ANY DaemonSet that uses hostPorts, pin `maxUnavailable >= 1, maxSurge: 0`. The
  convenience default of many charts (Traefik included) is the unsafe combination.
- This only bites when the pod template actually changes, which for a GitOps-managed
  Traefik is often the FIRST edit to its values after install — easy to misread as "my
  change broke Traefik" when it is really the rollout strategy. Here the change that
  exposed it was enabling `allowCrossNamespace` (see
  [central oauth2-proxy gate](../design-patterns/traefik-forwardauth-central-oauth2-proxy-gate.md)),
  which only took effect after being applied by hand (see
  [ArgoCD Applications are applied manually](../conventions/argocd-apps-applied-manually.md)).
- Observed on Traefik proxy v3.6.10, chart 39.0.5, on k3s.
