---
title: "Central oauth2-proxy + CILogon gate for multiple hosts behind Traefik forwardAuth"
date: 2026-07-07
category: docs/solutions/design-patterns/
module: kubernetes/oauth2-proxy
problem_type: design_pattern
component: authentication
severity: medium
applies_when:
  - "Gating two or more Traefik-fronted hosts behind a single oauth2-proxy that lives in its own namespace"
  - "Using oauth2-proxy as an OIDC client of CILogon (or any OIDC provider) for per-user auth"
  - "Wiring Traefik forwardAuth so an unauthenticated request redirects to the IdP instead of returning a bare 401"
  - "Authorizing a fixed set of people by identity rather than by network/IP"
related_components: [tooling]
tags: [oauth2-proxy, traefik, forwardauth, cilogon, oidc, cross-namespace, authentication]
---

# Central oauth2-proxy + CILogon gate for multiple hosts behind Traefik forwardAuth

## Context

Several Traefik-fronted operator surfaces (here: Grafana on its own subdomain and
Flower under a path on the apex host) needed per-user authentication, replacing an IP
allowlist. The chosen shape is ONE oauth2-proxy Deployment, in its own `oauth2-proxy`
namespace, acting as a confidential OIDC client of CILogon, with a dedicated auth host
serving `/oauth2/*`. Each protected surface's Ingress references a small Traefik
middleware chain that calls oauth2-proxy to decide access. Getting the redirect
behavior and the cross-namespace reference right is the non-obvious part.

## Guidance

**The middleware chain (per protected host):** `forwardAuth` -> `errors` -> `chain`.

1. `forwardAuth` middleware: `address` = oauth2-proxy's in-cluster
   `/oauth2/auth` URL. This endpoint returns **202** (valid, authorized session) or
   **401** (no/invalid session) — never 403.
2. `errors` middleware: scoped to **status 401 only**, `service` = a
   **cross-namespace** reference to the oauth2-proxy Service, `query` =
   `/oauth2/sign_in?rd={url}`, with `statusRewrites {401: 302}`. This turns a bare 401
   into a redirect to the sign-in flow, carrying the original URL as `rd`.
3. `chain` middleware composing `[errors, forwardauth]`, referenced from the Ingress
   annotation `traefik.ingress.kubernetes.io/router.middlewares`.

**Enable cross-namespace refs.** The `errors.service` reference points at oauth2-proxy
in a different namespace, so Traefik needs
`providers.kubernetesCRD.allowCrossNamespace: true` (a static provider option — it
requires a Traefik restart to take effect). Prefer this over
`allowExternalNameServices`, which permits arbitrary-DNS ExternalName services and is
SSRF-adjacent.

**Authorize on `sub`, not email.** Point oauth2-proxy's identity claim at the OIDC
subject with `--oidc-email-claim=sub` and gate with `--authenticated-emails-file`
(a roster of CILogon `sub` values). Never set `--email-domain` — `--email-domain=*`
ORs to allow-all and silently bypasses the roster. In federations like
CILogon/Internet2/eduGAIN, email is reassigned; `sub` is stable.

**Constrain redirects.** Set `--whitelist-domain` for every host the gate serves
(subdomain and apex). oauth2-proxy discards an `rd` outside the whitelist and falls
back to `/`, closing the open-redirect hole.

## Why This Matters

- **The 401-vs-403 detail prevents a redirect loop.** `/oauth2/auth` answers 202/401
  only. A user who authenticates at CILogon but is not on the roster is denied at
  `/oauth2/callback` with a **403 on the auth host** — and because the `errors`
  middleware is scoped to 401 only, that 403 is terminal, not another redirect. Scope
  the errors middleware to 403 as well and not-allowlisted users loop forever.
- **`{url}` must be the full URL.** The post-login return and whitelist matching depend
  on Traefik substituting `{url}` with scheme+host+path, not a bare path. Verified on
  Traefik v3.6.10; older Traefik versions substituted only the path.
- **One proxy, one client, one roster** fronting all surfaces means access is granted
  and revoked per person in one place, from any network.

## When to Apply

Use this when you have multiple Traefik-fronted surfaces to protect with per-user SSO,
an OIDC provider (CILogon or otherwise), and you want the proxy isolated in its own
namespace. If you have exactly one host and no cross-namespace boundary, a simpler
same-namespace forwardAuth without `allowCrossNamespace` suffices.

## Examples

In-cluster verification (before wiring a browser through it):

```bash
b=http://oauth2-proxy.oauth2-proxy.svc.cluster.local:4180
curl -s -o /dev/null -w '%{http_code}\n' $b/oauth2/auth               # -> 401 (never 403)
curl -s -D - -o /dev/null "$b/oauth2/sign_in?rd=https%3A%2F%2Fgrafana.example.org%2F" \
  | grep -i '^location:'      # -> 302 to https://<idp>/authorize?...&state=<nonce>:https://grafana.example.org/
curl -s -D - -o /dev/null "$b/oauth2/sign_in?rd=https%3A%2F%2Fevil.example.com%2F" \
  | grep -i '^location:'      # -> off-domain rd dropped; state carries ':/' , not the evil host
```

Through Traefik, an unauthenticated (cookieless) request to a protected host returns
`302` to the IdP with the full original URL preserved in `state`. A symptom that
`allowCrossNamespace` is NOT active is Traefik logging
`error while reading error page middleware ... service oauth2-proxy/oauth2-proxy is not
in the parent resource namespace <ns>` and the surface returning 500.

Related:
[cookie-secret byte length](../runtime-errors/oauth2-proxy-cookie-secret-byte-length.md),
[Traefik hostPort rollout deadlock](../integration-issues/traefik-hostport-daemonset-rollout-deadlock.md)
(enabling `allowCrossNamespace` is what triggered it),
[ArgoCD Applications applied manually](../conventions/argocd-apps-applied-manually.md).
