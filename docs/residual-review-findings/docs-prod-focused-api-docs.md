# Residual Review Findings — docs/prod-focused-api-docs

Source: `ce-code-review` (correctness, reliability, adversarial) plus the
`ce-doc-review` passes over
`docs/plans/2026-07-21-003-docs-prod-focused-api-docs-plan.md`.

Findings applied in the branch are omitted. These are the ones that were
report-only, human-owned, pre-existing, or deferred by explicit decision.

## Blocks the claim this branch publishes

- **P2 — The rate limit is published but never observed.** `docs/api/recent-crossmatch-api.md:17`
  tells the public that the production endpoint is deliberately unauthenticated
  *and* that a per-source-IP edge rate limit is the compensating control. That
  claim rests entirely on configuration read from the gitops repo
  (`apps/crossmatch-service/templates/middleware-ratelimit.yaml` renders under
  `web.enabled && !web.auth.enabled`; `values-prod.yaml` sets exactly that;
  `templates/ingress.yaml` attaches it). Nothing has observed an actual 429 from
  production. The plan's Verification Contract carries an
  "Edge rejection observed, not inferred" gate for precisely this, and that gate
  was **not run** — exercising it means deliberately exhausting a per-source-IP
  bucket that may be shared with an entire institution, which is not an
  autonomous call. Raised independently by the adversarial code reviewer and by
  the plan's adversarial doc reviewer.
  **Before merge:** trip the limit once from a controlled address and record the
  status, content type, body, and any `Retry-After`, then reconcile the Errors
  section against it.

## Deferred by decision

- **The future-auth notice names no announcement channel.** Raised by
  product-lens and security-lens during plan review; skipped deliberately — the
  notice stays a bare forward-looking statement.

## Design calls left to a human

- **P2 — A paged walk has no global retry budget, and failure discards every
  page already fetched.** `notebooks/recent_crossmatch_demo.ipynb` —
  `list(iter_all_objects(...))` throws away 40 pages of work on one final 429 or
  transport hiccup, and re-running re-spends the same shared rate-limit budget.
  Terminating but wasteful. (reliability)

- **P2 — The helper shape invites hardcoding a token when auth arrives.** The
  API doc tells readers to write clients so credentials can be added later, but
  the helper is a bare module-level `httpx.get` with no headers argument and no
  client object. The obvious edit when auth ships is to paste a literal token
  into a notebook cell, and notebooks are committed with their source.
  Consider adding an env-sourced auth seam before auth lands. (adversarial)

## Pre-existing, not introduced here

- **P3 — A 3xx reaches `resp.json()` unflagged.** httpx does not follow
  redirects by default and `raise_for_status()` only fires on 4xx/5xx, so a
  captive portal or interception proxy yields a bare `JSONDecodeError` about an
  HTML body rather than anything mentioning a login page. (adversarial)

- **P3 — `iter_all_objects`' docstring contradicts the params it sends.** The
  docstring says only the cursor is sent after the first page; the code also
  sends `page_size`. The code is correct — `page_size` is deliberately not
  pinned by the cursor — but a reader copying the helper may strip it and
  silently fall back to the server default mid-walk. (correctness)

- **P3 — The cursor walk cannot terminate if the server repeats a cursor.** The
  only loop exit is `next_cursor: null`. A paging regression that repeats a
  cursor becomes an infinite loop, and the new retry makes it more patient and
  therefore less obvious. (reliability)

## Coverage note

The retry helper lives in notebook JSON, outside `crossmatch/pytest.ini`'s
`testpaths`, so none of its behavior is reachable by CI. It was verified by a
throwaway stub harness run outside the repo (15 scenarios, all passing,
including negative / zero / NaN / infinity / HTTP-date `Retry-After`). A future
edit to the helper has no automated backstop.
