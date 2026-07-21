# Residual Review Findings -- fix/crossmatch-single-catalog-resilience

Findings from the ce-code-review pass that were deliberately NOT applied in this
PR, recorded so they are durable. The blocking P1 (deterministic errors were
being swallowed as skips instead of failing loud) was found by 4 independent
reviewers, fixed in this PR, and covered by a regression test
(`test_deterministic_error_fails_loud_not_skipped`). Everything below is either
an accepted design decision from the plan or a pre-existing condition.

## Accepted design decisions (plan KTDs)

- **Zero-match alerts carry no coverage mark.** An alert that matched nothing in
  the catalogs that *did* read produces no notification, so it carries no
  `catalogs_skipped`/`partial` mark even when its batch was partial. A downstream
  consumer cannot distinguish "not checked against catalog X" from "no match in
  X" for such an object. This follows KTD6 (coverage mark rides only on published
  notifications) -- adding a zero-match coverage signal was out of scope.
  Reviewers: correctness (P3), adversarial (P3).

- **No-overlap counts as a success for the >=1-success guard.** If every
  data-bearing catalog fails transiently but one catalog reports no-overlap, the
  batch completes MATCHED (partial=true) rather than reverting. Reverting a
  no-overlap batch would poison-pill into an infinite retry against a footprint
  that will never overlap, so counting it as success is deliberate. The
  observability gap (a near-total outage can look like a normal quiet batch from
  published output) is real but accepted; distinguishing "real read" from
  "no-overlap read" in the completion log is a possible follow-up.
  Reviewer: adversarial (P4).

- **`partial`/`catalogs_skipped` are batch-level and not self-describing per
  message.** A single message carries no batch id or total-catalog count, so a
  consumer reading one message in isolation cannot correlate it with sibling
  matches or compute total coverage. This is now documented in
  `scimma_crossmatch_service_design.md` and `docs/api/recent-crossmatch-api.md`.
  Adding a batch id / catalog-count field is a larger contract decision, out of
  scope. Reviewer: api-contract (P2).

## Pre-existing (not introduced by this change)

- **Per-catalog `CatalogMatch` writes commit outside the final atomic block.**
  `CatalogMatch.objects.bulk_create(...)` runs inside the catalog loop; only the
  `Notification` writes + the MATCHED transition are atomic at the end. So a
  crash (or the >=1-success guard raising) after some catalogs wrote their
  matches leaves `CatalogMatch` rows committed for an alert that reverts to
  INGESTED. This predates this change and is idempotent-safe (the
  `unique_catalog_match` constraint + `ignore_conflicts=True` make re-dispatch
  non-duplicating). This change *widens the window* -- every catalog is now
  attempted rather than aborting on the first failure -- so more matches can be
  committed before a later failure. Follow-up candidate: buffer all
  `matches_to_create` across catalogs and bulk_create once inside the final
  atomic block (symmetric to how `all_notifications` is already accumulated).
  Reviewer: reliability (P2, pre-existing).

## Accepted operational note

- **A persistently-failing catalog logs one warning per batch.** Intentional:
  the `crossmatch_catalog_skips_total` counter is the alerting mechanism
  (rate-based), and the per-batch warning is an audit trail (now carrying
  `error=str(exc)` for diagnosis). Reviewer: reliability (P3).
