---
title: "oauth2-proxy CrashLoops when the cookie secret is 44 bytes (openssl rand -base64 32)"
date: 2026-07-07
category: docs/solutions/runtime-errors/
module: kubernetes/oauth2-proxy
problem_type: runtime_error
component: authentication
severity: high
symptoms:
  - "oauth2-proxy pod in CrashLoopBackOff immediately after start"
  - "Log line 'invalid configuration: cookie_secret must be 16, 24, or 32 bytes to create an AES cipher, but is 44 bytes'"
root_cause: config_error
resolution_type: config_change
related_components: [tooling]
tags: [oauth2-proxy, cookie-secret, sealedsecret, kubeseal, aes, cilogon]
---

# oauth2-proxy CrashLoops when the cookie secret is 44 bytes

## Problem

oauth2-proxy refuses to start and CrashLoopBackOffs because its cookie secret is the
wrong length for an AES key.

## Symptoms

- The pod restarts repeatedly (`CrashLoopBackOff`).
- `kubectl -n oauth2-proxy logs deploy/oauth2-proxy`:
  `invalid configuration: cookie_secret must be 16, 24, or 32 bytes to create an AES cipher, but is 44 bytes`.

## What Didn't Work

Generating the cookie secret with the "obvious" command:

```bash
openssl rand -base64 32        # WRONG for oauth2-proxy
```

`openssl rand -base64 32` produces 32 random BYTES base64-ENCODED into a
44-CHARACTER string. oauth2-proxy measures the literal length of the value it is handed
(44) — it does not base64-decode a standard-alphabet (`+` / `/`) secret back to 32
bytes — so it sees a 44-byte key and rejects it. The `-base64 32` form is what most
quick-start snippets show, which is exactly why this trap is common.

## Solution

Generate a secret whose literal length is exactly 16, 24, or 32 bytes. The simplest is
16 random bytes rendered as 32 hex characters:

```bash
openssl rand -hex 16          # 32 hex chars == 32 bytes -> accepted
```

Re-seal it — piping straight into `kubeseal` keeps the plaintext out of the terminal
and transcript; only the encrypted blob is printed — then paste it into the SealedSecret
and let ArgoCD unseal it:

```bash
openssl rand -hex 16 | tr -d '\n' | kubeseal --raw \
  --controller-name sealed-secrets --controller-namespace kube-system \
  --scope namespace-wide --namespace oauth2-proxy
# -> paste as encryptedData.cookie-secret
```

## Why This Works

AES keys must be 16, 24, or 32 bytes (AES-128/192/256). oauth2-proxy validates the
cookie secret's byte length against that set at startup. A 32-hex-character string is
32 bytes exactly. (A base64 value only works if oauth2-proxy decodes it to a valid key
length; handing it a value that is already the right byte count is the unambiguous
path.)

## Prevention

- Document the generation command right next to the secret so the next person does not
  reach for `-base64 32`. Here the SealedSecret header and the oauth2-proxy README both
  call out `openssl rand -hex 16` explicitly.
- Only the cookie secret has a length constraint. The CILogon client secret does not —
  do not re-seal the client secret chasing this error.
- This secret is consumed by the
  [central oauth2-proxy gate](../design-patterns/traefik-forwardauth-central-oauth2-proxy-gate.md).
