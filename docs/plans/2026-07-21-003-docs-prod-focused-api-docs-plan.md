---
title: PROD-Focused Recent Crossmatch API Docs - Plan
type: docs
date: 2026-07-21
topic: prod-focused-api-docs
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-brainstorm
execution: code
---

# PROD-Focused Recent Crossmatch API Docs - Plan

## Goal Capsule

- **Objective:** Make `docs/api/recent-crossmatch-api.md` and `notebooks/recent_crossmatch_demo.ipynb` read as production artifacts for science users, pointed at `https://crossmatch.scimma.org`, with no reference to the DEV service.
- **Product authority:** Maintainer (Scott Koranda). The Product Contract below is authoritative for behavior; the Planning Contract is authoritative for how it is built.
- **Product Contract preservation:** changed: R6 — now names HTTP 429 explicitly instead of "the rate-limit rejection status". A clarification of the same requirement, not a scope change.
- **Execution profile:** Two files, no application code, no deployment change. Documentation edits plus one behavioral change to notebook helper code.
- **Stop conditions:** Stop and ask if the work would require changing the endpoint's auth posture or rate-limit configuration, editing anything outside `docs/api/recent-crossmatch-api.md` and `notebooks/recent_crossmatch_demo.ipynb`, or altering a statement R7 protects.
- **Tail ownership:** Maintainer owns the branch push, the pull request, and the merge. See the project's git workflow — `upstream` and `main` are off-limits.
- **Open blockers:** None.

---

## Product Contract

### Summary

Refocus the public API reference and the demo notebook on the production service at `https://crossmatch.scimma.org`, removing every mention of DEV. The posture text becomes a plain statement of how production behaves today — public, no credentials, rate-limited — paired with a notice that authentication and authorization will be required in a future release.

### Problem Frame

Both artifacts were written when DEV was the only deployment. They hardcode `crossmatch-dev.scimma.org`, and the API doc's auth paragraph is framed as a DEV-specific concession: it says the endpoint is public "on DEV", that rate limiting is deferred, and that the reader should not assume the posture on a non-DEV deployment.

PROD is now live and serves the same endpoint. It is public and unauthenticated by a reviewed, deliberate opt-out, and it carries a per-source-IP edge rate limit that DEV's text describes as not yet existing. So the doc is wrong in three independent ways at once: the host is wrong, the "rate limiting deferred" claim is false in production, and the hedge that carried the forward-looking warning is attached to an environment distinction the reader should no longer see.

These are the two artifacts a scientist actually opens. A reader who follows them today reaches a development instance whose availability and data are not guaranteed, and gets no signal that an aggressive or highly parallel client — or one behind shared institutional egress — can be rejected at the edge.

### Key Decisions

- **Zero DEV mention in both artifacts.** Every URL, example, and caveat refers to production only; the notebook does not carry DEV as a commented alternative. These are science-user artifacts, and the development team already knows its own hostname. (session-settled: user-directed — chosen over a one-line DEV pointer and over an explicit Environments table: neither earns its space in a scientist-facing doc.)

- **Document that a rate limit exists, without naming its values.** The doc states that a per-source-IP edge rate limit applies and that an aggressive client can be rejected and should back off, but does not name the sustained rate or burst. Those values live in the deployment overlay and are marked tunable there; naming them in the doc guarantees eventual drift with no way for a reader to tell. (session-settled: user-directed — chosen over stating the concrete values and over omitting rate limiting entirely.)

- **Announce future authentication without a date or mechanism.** The doc says authentication and authorization will be required in a future release and that clients should expect to add credentials, but names no timeline, release, or auth scheme. A public doc that commits to a date creates an obligation the project has not made. (session-settled: user-directed.)

- **The notebook is committed source-only, with outputs stripped.** A reader gets a notebook that runs fresh rather than one carrying a frozen snapshot of one day's production data. (session-settled: user-directed — chosen over committing a fresh PROD execution: stale counts drift and inflate diffs.)

- **The paging helper models correct client behavior.** `iter_all_objects` is the code scientists copy into their own work, so it handles rate-limit rejection with a bounded backoff-and-retry — scoped to that one status, capped in attempts, re-raising when the cap is reached. An unbounded retry would be worse than the current raise: it turns a persistent rejection into a silent hang. Demonstrating the failure mode the doc now documents is worth the few lines it costs.

### Requirements

**API reference (`docs/api/recent-crossmatch-api.md`)**

- R1. The documented endpoint URL is `https://crossmatch.scimma.org/api/recent-crossmatches`.
- R2. No text in the document refers to a DEV service, a DEV host, or a DEV-specific posture.
- R3. The auth-posture text states as present fact that the endpoint is public and unauthenticated and requires no credentials.
- R4. The same text states that authentication and authorization will be required in a future release, without naming a date, release, or mechanism, and advises clients to expect to add credentials.
- R5. The document states that a per-source-IP edge rate limit bounds request rate, in addition to the existing per-page and window-span bounds on per-request cost, and prescribes the client response to a rejection: exponential backoff with jitter, honoring `Retry-After` when present, capped at a finite number of attempts.
- R6. The Errors section documents the rate-limit rejection as HTTP 429, and states that it is emitted by the edge proxy rather than the application, so unlike the invalid-parameter and wrong-method responses it carries no `{"error": ...}` JSON body and must be detected by status code alone.
- R7. The existing statements about paging semantics, cursor opacity, detail levels, and batch-coverage fields are preserved unchanged; only the host, posture, and rate-limit text change.

**Demo notebook (`notebooks/recent_crossmatch_demo.ipynb`)**

- R8. `BASE_URL` is the production host, and no cell or comment names a DEV host.
- R9. The introductory markdown states the endpoint is public and needs no credentials, and carries the same future-authentication notice as R4.
- R10. The paging helper retries only the rate-limit rejection status, using exponential backoff with jitter and honoring `Retry-After` when present, up to a fixed maximum number of attempts, after which it re-raises; every other error propagates immediately.
- R11. The committed notebook has all cell outputs cleared, and the stray empty trailing cell in the working tree is removed.
- R12. The notebook remains runnable top to bottom against the production endpoint with no edits.

### Acceptance Examples

- AE1. Reader follows the doc's endpoint URL.
  - **Covers R1, R2.**
  - **Given** a scientist reading `docs/api/recent-crossmatch-api.md` for the first time,
  - **When** they copy any URL or example from it,
  - **Then** the request goes to `crossmatch.scimma.org`, and nothing in the document suggests another environment exists.

- AE2. Client writer plans for future auth.
  - **Covers R3, R4, R9.**
  - **Given** a developer writing a long-lived client against the endpoint,
  - **When** they read the posture text in either artifact,
  - **Then** they learn no credentials are needed today and that credentials will be required later, and they find no date or auth scheme to design against.

- AE3. A client is rejected for exceeding the rate limit.
  - **Covers R5, R6, R10.**
  - **Given** a client whose request rate has exceeded the edge limit — a parallel fetcher, or a walk from an address sharing institutional egress,
  - **When** the edge rejects a page,
  - **Then** the helper backs off and retries the rejection alone, re-raising once its attempt cap is reached rather than looping, and the API doc's Errors section explains the status and its missing JSON body.

- AE4. Reference content survives the revision.
  - **Covers R7.**
  - **Given** the revised `docs/api/recent-crossmatch-api.md`,
  - **When** it is diffed against the version before this work,
  - **Then** the only changed passages are the host, the auth-posture text, and the rate-limit text; the paging, cursor-opacity, detail-level, and batch-coverage statements are byte-identical.

- AE5. Notebook names production and nothing else.
  - **Covers R8.**
  - **Given** the revised notebook,
  - **When** its source is scanned for hostnames,
  - **Then** `BASE_URL` is the production host and no cell, comment, or markdown string contains a DEV hostname.

- AE6. Notebook is committed source-only.
  - **Covers R11.**
  - **Given** the notebook as staged for commit,
  - **When** its cells are inspected,
  - **Then** every cell's outputs are empty and no trailing empty cell remains.

- AE7. Notebook runs clean against production.
  - **Covers R12.**
  - **Given** a fresh checkout of the output-stripped notebook,
  - **When** it is executed top to bottom with no edits,
  - **Then** every cell completes against `crossmatch.scimma.org` without error.

### Scope Boundaries

- The historical plan documents under `docs/plans/`, `scimma_crossmatch_service_design.md`, and the ideation documents keep their DEV references. They are point-in-time records, and rewriting them would falsify history.
- The `DJANGO_ALLOWED_HOSTS` default in `crossmatch/project/settings.py` still names the DEV host. The deployment supplies the value explicitly per environment, so the default is inert; changing it is a separate concern from documentation.
- No change to the endpoint's behavior, auth posture, or rate-limit configuration. This work documents what is already deployed.
- Actually implementing authentication is out of scope; R4 announces it, nothing more.

### Dependencies / Assumptions

- The production endpoint is live and publicly reachable. Verified 2026-07-21: `GET https://crossmatch.scimma.org/api/recent-crossmatches?detail=ids&page_size=2` returns HTTP 200 with populated results.
- Production's public posture is a reviewed decision, not an oversight — recorded in the deployment overlay's `web.auth.enabled: false` with a comment dating it to 2026-07-14.
- The edge rate limit is rendered only for an unauthenticated API, so it is active in production today.
- The notebook's uncommitted working-tree changes are cell outputs plus one empty trailing cell, with no source edits. Verified by comparing each cell's source against `HEAD`; stripping outputs discards no work.

### Sources / Research

- `docs/api/recent-crossmatch-api.md` — the document being revised; its Endpoint, Bounds, Errors, and Paging sections are what R7 protects.
- `notebooks/recent_crossmatch_demo.ipynb` — cell 0 (intro markdown), cell 1 (`BASE_URL` and the DEV comment), cell 13 (`iter_all_objects`), and the stray empty trailing cell R11 removes are the cells R8-R11 touch.
- `crossmatch-service-k8s-gitops` sibling repo: `apps/crossmatch-service/values-prod.yaml` (production host, `web.enabled`, `web.auth.enabled`), `templates/middleware-ratelimit.yaml` (the edge rate limit and the condition under which it renders), and `templates/ingress.yaml` (where the middleware is attached).
- `docs/plans/2026-07-13-001-feat-recent-crossmatch-api-plan.md` — KTD5 records why the API's auth posture is a dedicated, secure-by-default flag independent of the Flower gate; the reason production's public posture had to be an explicit opt-out.
- `crossmatch/matching/catalog.py:77` (`_read_with_retry`) and `crossmatch/brokers/lasair/consumer.py:43-61` — the repo's two existing bounded-retry implementations. KTD2 mirrors their shape.

---

## Planning Contract

### Key Technical Decisions

- KTD1. **Edit both artifacts in place; introduce no new files.** The API reference is prose surgery on three passages, and the notebook change is confined to three cells plus an output strip. Nothing here justifies a new module, script, or shared helper.

- KTD2. **Model the retry on the repo's existing bounded-retry shape, not a new dependency.** The notebook's `get_recent` wraps `httpx`. `crossmatch/matching/catalog.py:77` establishes the convention the helper follows: a narrow retry gate that matches only the transient condition, a capped attempt count, sleep between attempts, and an immediate re-raise for everything else; `crossmatch/brokers/lasair/consumer.py:43-61` establishes exponential backoff with a ceiling. Two alternatives were considered and rejected. `tenacity` would add a dependency to a demo notebook that the service itself does not use. `httpx.HTTPTransport(retries=...)` is the client-native option, but it retries connection failures only — it never sees a completed response, so it cannot gate on HTTP 429, which is exactly the condition R10 requires.

- KTD3. **Put the retry in the shared request helper, not only in the paging loop.** Every notebook cell issues its requests through `get_recent`, which calls `raise_for_status()`. Implementing the retry there satisfies R10 — the paging helper retries, through its request path — and leaves `iter_all_objects` a thin cursor loop, while every other cell gains the same protection. Implementing it inside `iter_all_objects` instead would either duplicate the request logic or leave the single-request cells still raising on a rejection. The consequence to manage: the attempt budget is per request, so a sustained-throttling walk never exhausts it and would crawl silently. The per-retry notice in U3 is what keeps that visible rather than looking like a frozen cell.

- KTD4. **Retry constants are notebook-local literals.** The service reads its retry bounds from Django settings (`CROSSMATCH_READ_RETRIES`, `CROSSMATCH_READ_RETRY_BACKOFF_SECONDS`), but a standalone notebook has no settings to read and adding a config layer to a demo would obscure the very code readers are meant to copy. Values: 5 attempts, 1s initial delay, doubling, 30s ceiling, with jitter. (session-settled: user-approved — chosen over settings-driven or environment-driven configuration: a demo notebook's constants should be readable inline.)

- KTD5. **Zero DEV mention in both artifacts.** (session-settled: user-directed — chosen over a one-line DEV pointer and over an explicit Environments table: neither earns its space in a scientist-facing doc. Instantiates the Product Contract Key Decision of the same name.)

- KTD6. **Document that a rate limit exists without naming its values.** (session-settled: user-directed — chosen over stating the concrete values and over omitting rate limiting entirely: the values live in the deployment overlay and are marked tunable. Instantiates the Product Contract Key Decision of the same name.)

- KTD7. **Announce future authentication with no date or mechanism.** (session-settled: user-directed — chosen over naming a target release: a public doc that commits to a date creates an obligation the project has not made. Instantiates the Product Contract Key Decision of the same name.)

- KTD8. **Commit the notebook source-only with outputs stripped.** (session-settled: user-directed — chosen over committing a fresh production execution: stale counts drift and inflate diffs. Instantiates the Product Contract Key Decision of the same name.)

### Assumptions

- **The rate-limit rejection is HTTP 429.** This is Traefik's `rateLimit` default and was read from the deployment overlay, which declares only `average` and `burst` and never states a status. R6's Errors entry, U1's prose, U3's retry gate, and U3's stub scenarios all use 429 literally. The Verification Contract's edge-observation gate confirms it against a real response before publication.

- The rate-limit rejection carries no `Retry-After` header. Traefik's `rateLimit` middleware does not emit one, so the helper's `Retry-After` handling is defensive: it honors the header if a future edge configuration supplies one and falls back to its own backoff otherwise. R5 and R10 are worded conditionally ("when present") so neither becomes false either way. The edge-observation gate records whether the header is in fact absent.

- The two assumptions above are inferred from configuration, not observation. Every other rate-limit check in this plan runs against a stub the implementer writes to match them, so nothing else in the Verification Contract can falsify them — which is why the edge-observation gate exists.

### Sequencing

U1 and U2 are independent prose edits and can land in either order, but U2 must land before U3 since both edit cell 1. U3 changes notebook code and should land before U4, because U4's output strip must capture the notebook in its final source state. U4 is last, and its cold-run check executes a copy outside the working tree so the strip remains the final mutation on the tracked file.

---

## Implementation Units

### U1. Rewrite the API reference for production

- **Goal:** `docs/api/recent-crossmatch-api.md` describes the production endpoint, its current posture, and its rate-limit behavior, with no DEV reference.
- **Requirements:** R1, R2, R3, R4, R5, R6, R7. Covers AE1, AE2, AE4.
- **Dependencies:** none.
- **Files:** `docs/api/recent-crossmatch-api.md` (modify).
- **Approach:** Three passages change and nothing else. The Endpoint block's URL becomes the production host. The paragraph beneath it — currently the DEV-specific posture concession — becomes a present-tense statement that the endpoint is public and needs no credentials, that per-request cost is bounded by the page-size and window-span caps, that a per-source-IP edge rate limit bounds request rate, and that authentication and authorization will be required in a future release without naming a date, release, or scheme. It also prescribes the client response to a rejection per KTD2's shape. The Errors section gains HTTP 429, marked as edge-emitted and therefore carrying no `{"error": ...}` body. Leave the Query parameters, Bounds, Response, detail-level, and Paging sections untouched — R7 protects them.
- **Patterns to follow:** the document's existing voice — declarative, second-person-free, backtick-quoted parameter names.
- **Test scenarios:**
  - Covers AE1. A `grep` for `crossmatch-dev` over the file returns no matches, and every fenced URL example names `crossmatch.scimma.org`.
  - Covers AE2. The posture paragraph states both that no credentials are needed today and that they will be required later; it contains no date, no release number, and no auth-scheme name.
  - Covers AE4. `git diff` on the file shows changed hunks only in the Endpoint block, the posture paragraph, and the Errors section; the Paging, Bounds, and detail-level sections are unchanged.
  - The Errors section names HTTP 429 and states it carries no JSON error body, so a reader cannot conclude the `{"error": ...}` envelope is universal.
- **Verification:** A reader who knows nothing of DEV can follow the document end to end, reach production, and correctly predict what a rate-limit rejection looks like.

### U2. Repoint and reframe the notebook prose

- **Goal:** The notebook's `BASE_URL` and introductory markdown describe production only.
- **Requirements:** R8, R9. Covers AE2, AE5.
- **Dependencies:** none. U2 sources its posture text from R4 directly, not from U1's prose, so the two units are genuinely order-independent.
- **Files:** `notebooks/recent_crossmatch_demo.ipynb` (modify — cell 0 markdown, cell 1 `BASE_URL` and its comment).
- **Approach:** `BASE_URL` becomes the production host. The comment above it currently names DEV as the default and a local server as the alternative; drop the DEV half and keep the local-server note, which is not a DEV reference. Cell 0's markdown says the endpoint is "public/unauthenticated on DEV" and tells the reader to point `BASE_URL` at the DEV host — both go. In their place, write R4's content in the notebook's own register: the endpoint is public and needs no credentials today, and authentication and authorization will be required in a future release, with no date, release, or scheme named.
- **Patterns to follow:** cell 0's existing prose register — short paragraphs addressed to a scientist, backticks for identifiers.
- **Test scenarios:**
  - Covers AE5. A scan of every cell's source for `crossmatch-dev` and for a standalone `DEV` token returns nothing, in code, comments, and markdown alike.
  - Covers AE2. Cell 0 states both halves R4 requires — no credentials today, credentials later with no date or scheme — so a reader who opens only the notebook still learns credentials are coming.
  - `BASE_URL` resolves to `https://crossmatch.scimma.org` and `ENDPOINT` builds the documented path from it.
- **Verification:** The notebook read top to bottom describes one environment.

### U3. Bounded retry in the notebook's request path

- **Goal:** A rate-limit rejection is retried a bounded number of times with backoff; every other failure surfaces immediately.
- **Requirements:** R10, R12. Covers AE3.
- **Dependencies:** U2 (both edit cell 1; sequencing them avoids a conflicting edit).
- **Files:** `notebooks/recent_crossmatch_demo.ipynb` (modify — cell 1 `get_recent`, cell 13 `iter_all_objects` docstring).
- **Approach:** Per KTD3, the retry lives in `get_recent`. On an HTTP 429 response, sleep and re-issue, up to the KTD4 attempt cap; on the final attempt, raise. Every other non-2xx status raises on the first attempt through the existing `raise_for_status()` path — the retry gate matches 429 and nothing else, mirroring `_read_with_retry`'s transient-only discipline. Compute the delay as exponential backoff from the initial delay, doubling to the ceiling, with jitter so concurrent readers do not retry in lockstep. `Retry-After` is honored when present but parsed as delta-seconds only: a non-numeric or HTTP-date value falls back to the computed backoff, and the honored delay is clamped to KTD4's ceiling so no server-supplied value can extend a single sleep past the documented bound. Print a one-line notice on each retry naming the attempt number and the sleep duration, mirroring `_read_with_retry`'s per-retry log, so a throttled walk reads as waiting rather than stalled. Update `iter_all_objects`'s docstring to note that rate-limit handling lives in the request helper, so a reader copying the paging loop knows where the behavior comes from.
- **Execution note:** The retry gate's narrowness is the property worth proving first — a helper that retries a malformed-cursor `400` is worse than one that does not retry at all. Exercise the non-retry path before the retry path.
- **Patterns to follow:** `crossmatch/matching/catalog.py:77` for the attempt loop, narrow gate, and re-raise; `crossmatch/brokers/lasair/consumer.py:43-61` for doubling backoff with a ceiling.
- **Test scenarios:** the notebook is outside `pytest.ini`'s `testpaths`, so these are executed by hand rather than as pytest cases. Every rate-limit scenario runs against a stub — none may intentionally trip the production edge, which would deny service to everyone sharing the source address. The stub lives in a throwaway script outside the repository working tree (KTD1 forbids new files in the repo); record the results in the commit or PR body rather than committing the script.
  - Covers AE3. A stub returning 429 twice, then 200, yields the 200 payload after two sleeps, and the caller sees no exception.
  - A stub returning 429 on every attempt raises after exactly the configured attempt count, rather than looping — measured by counting stub invocations.
  - A stub returning `400` with a malformed-cursor body raises on the first call with no sleep, proving the gate does not widen.
  - A stub supplying `Retry-After: 2` causes a 2-second wait rather than the computed backoff.
  - A stub supplying `Retry-After: 86400` sleeps no longer than the KTD4 ceiling, proving the clamp holds.
  - A stub supplying an HTTP-date `Retry-After` falls back to the computed backoff without raising.
  - Two stubbed concurrent walkers do not retry in lockstep, confirming jitter is applied.
  - Each retry emits a one-line notice naming the attempt number and sleep duration.
  - A live `get_recent()` with no parameters returns a populated page, confirming the retry wrapper did not break the ordinary success path. This is the only live call in U3.
- **Verification:** A persistent rejection ends in a raised error with a readable message, and a transient one is invisible to the caller.

### U4. Strip outputs and remove the trailing cell

- **Goal:** The committed notebook is source-only and carries no stray cell.
- **Requirements:** R11, R12. Covers AE6, AE7.
- **Dependencies:** U2, U3 — the strip must capture the notebook's final source state.
- **Files:** `notebooks/recent_crossmatch_demo.ipynb` (modify).
- **Approach:** Clear every cell's outputs and reset execution counts, then delete the empty trailing cell that currently sits after `iter_all_objects`. Confirm the cell count drops from 16 to 15 and that the three cells U2 and U3 edited retain their new source. The AE7 cold run executes a **copy** of the finished notebook outside the working tree — executing in place would write outputs and execution counts straight back into the tracked file, undoing the strip and committing a snapshot of production data. The output strip is the last action performed on the tracked file.
- **Test scenarios:**
  - Covers AE6. Every cell's outputs list is empty and every execution count is null.
  - Covers AE6. The notebook has 15 cells and the last one is not an empty code cell.
  - Covers AE7. A fresh top-to-bottom execution of a copy, outside the working tree, completes every cell against production without error.
  - After the AE7 run, the tracked notebook is re-checked: still 15 cells, still no outputs, still null execution counts.
  - `git diff` shows the notebook's source changes from U2 and U3 survived the strip.
- **Verification:** The committed notebook opens clean and runs from a cold start.

---

## Verification Contract

| Gate | Command or check | Applies to |
|---|---|---|
| No DEV references survive | `grep -rnE "crossmatch-dev\|\bDEV\b" docs/api/recent-crossmatch-api.md notebooks/recent_crossmatch_demo.ipynb` returns nothing (case-sensitive, so the standalone token catches DEV-framed prose without matching "developer" or "device") | U1, U2 |
| Protected content unchanged | `git diff docs/api/recent-crossmatch-api.md` — changed hunks confined to the Endpoint block, posture paragraph, and Errors section | U1 |
| Posture text carries both halves | The doc's posture paragraph and notebook cell 0 each state that no credentials are needed today and that they will be required later, with no date, release, or scheme named | U1, U2 |
| Edge rejection observed, not inferred | Trip the limit once from a controlled source address — not shared institutional egress — and record the actual status, content type, body, and any `Retry-After`; reconcile R6 and the Assumptions entries against what came back | U1, U3 |
| Notebook is source-only | Every cell's `outputs` is empty, every `execution_count` is null, cell count is 15, last cell is not an empty code cell | U4 |
| Notebook runs cold | Execute a **copy** outside the working tree, top to bottom against `https://crossmatch.scimma.org` with no edits; every cell completes. Re-check the tracked file afterward — it must still be output-free | U3, U4 |
| Retry gate is narrow and bounded | Hand-run all U3 stub scenarios from the throwaway script: 429 retries and raises at the cap; `400` raises immediately with no sleep; oversized and date-form `Retry-After` both stay within the ceiling; each retry prints its notice | U3 |
| No regression in the service | `docker compose --env-file docker/.env -f docker/docker-compose.yaml run --rm --no-deps celery-worker sh -c 'pip install -q -r requirements.dev.txt && python -m pytest'` — expected to be unaffected, since no file under `crossmatch/` is touched | all |

---

## Definition of Done

- Every requirement R1-R12 is satisfied and every acceptance example AE1-AE7 has been exercised.
- Both artifacts point at production and carry no DEV service or host reference. (The notebook's local-server note is not a DEV reference and stays.)
- The API reference's posture text states the present public posture, the rate limit, and the coming authentication requirement, and its Errors section describes HTTP 429 accurately including its missing JSON body.
- The notebook's request helper retries only HTTP 429, is bounded in attempts and in per-sleep duration, announces each retry, and re-raises on exhaustion.
- The committed notebook has no outputs and no trailing empty cell, and runs top to bottom against production from a cold start.
- No file outside `docs/api/recent-crossmatch-api.md` and `notebooks/recent_crossmatch_demo.ipynb` is modified.
- No experimental or dead-end code from abandoned attempts remains in the diff — the notebook in particular should carry no leftover debugging cells.
- Work is committed on a branch, not `main`. The push, pull request, and merge stay with the maintainer.

---

## Risks & Dependencies

- **The rate-limit text is coupled to the auth posture it announces.** The edge middleware renders only while the API is unauthenticated, so the day R4's future authentication lands, R5's rate-limit statement and R3's public-posture statement can both become false at once. Whoever implements authentication must revise both passages; nothing in the deployment overlay will prompt it.
- **The retry helper ships untested by CI.** The notebook sits outside `pytest.ini`'s `testpaths`, so U3's scenarios are hand-run once and never again. A future edit to the helper has no automated backstop. Extracting it into an importable module would fix this and was held out as disproportionate for a demo; revisit if the helper grows.
- **The rate limit is per source IP.** Readers behind campus NAT, a shared JupyterHub, or CI runners draw on one bucket, so they can be rejected at a far lower personal request rate than the doc's framing implies.
