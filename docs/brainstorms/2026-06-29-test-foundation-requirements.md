---
date: 2026-06-29
topic: test-foundation
---

# Test Foundation for crossmatch-service — Requirements

## Summary

Stand up a real automated-test foundation for `crossmatch-service` — a pytest-django +
factory_boy harness with reusable factories for the alert → match → notification graph —
and on it a first set of high-value logic tests centered on the crossmatch→notify pipeline,
wired to run automatically in CI. Add a dependency-pinning guard so a breaking transitive
version (like the `hats` skew) can't silently slip in. The suite is near-empty today; this
establishes the floor that future tests build on.

## Problem Frame

The service shipped three production-class bugs in a single session, all in the
crossmatch→notify path, all *silent* — the coarse signal (alerts marked `MATCHED`, counts
climbing) looked healthy while a specific path produced wrong results:

- a transitive dependency (`hats`) drifted to an incompatible version, so every catalog
  open threw and was swallowed — 350k alerts matched nothing;
- the `MATCHED→NOTIFIED` transition filtered on the wrong key and silently advanced nothing;
- notifications were committed before the alert reached `MATCHED`, stranding single-match
  alerts.

The suite that should have caught the two logic bugs is effectively one file
(`crossmatch/brokers/pittgoogle/tests.py`), run by hand in-container; `docs/developer.md`
even points at a `crossmatch.tests.crossmatch` module that doesn't exist. Nothing runs
tests automatically, so even existing coverage can't gate a regression. The cost is
recurring silent-correctness failures found only by manual DB inspection in production.
This effort guards the known recurring instances; a general guard against the
silent-failure *class* (end-to-end reconciliation or a runtime invariant) is out of scope
here and tracked as an open question.

## Key Decisions

- **pytest + pytest-django + factory_boy, not bare `TestCase`.** The suite is
  near-greenfield, so there's little convention to preserve, and the tests we need are
  almost all DB-state assertions where fixtures, `parametrize`, and factories pay off
  (e.g., one state-machine test parametrized over single- vs multi-match). The lone
  existing `TestCase` keeps running under pytest-django unchanged. Cost: a few dev deps and
  a second convention — cheap on an empty suite.
- **Not every error class is a unit test.** The logic bugs are unit/integration-testable
  against the DB; the `hats` version skew is not — a unit test passes in CI while the
  deployed env drifts. That class is handled by a dependency pin/lockfile, not a test.
- **Tests gate in CI.** A green suite that never runs automatically rots. CI gating in the
  app repo (a Postgres-backed job) is in scope; a failing test blocks merge.
- **Logic tests isolate external systems.** Dask compute, Kafka publish, and HATS catalog
  reads are mocked at clean seams so tests are fast, deterministic, and network-free.

## Requirements

**Test harness foundation**

- R1. Adopt pytest + pytest-django as the test framework and factory_boy for test data; the
  existing `crossmatch/brokers/pittgoogle/tests.py` continues to run unchanged.
- R2. Provide reusable factories/fixtures for the alert → CatalogMatch → Notification graph,
  able to construct an alert at any pipeline status in a few lines.
- R3. Tests run against a throwaway test database and isolate external systems (Dask, Kafka,
  HATS reads); no test depends on the network, a live broker, or the Dask cluster.
  Transaction-sensitive tests (R5, R9) use real commit semantics, not the default per-test
  rollback — see R5.

**Logic coverage (regressions for this session's bugs + adjacent fragile logic)**

- R4. The notify transition: an alert whose notifications are all sent advances
  `MATCHED→NOTIFIED`; an alert with any unsent notification does not. Regression for the
  pk-vs-natural-key transition bug.
- R5. The notify/matched ordering invariant: a notification is not dispatchable before its
  alert is `MATCHED`, and a single-match alert still reaches `NOTIFIED` even if dispatch
  runs while the alert is `QUEUED`. Regression for the commit-ordering race. This test must
  run under real commit semantics (`TransactionTestCase` / `django_db(transaction=True)`
  with `captureOnCommitCallbacks`, against Postgres); the default per-test rollback
  collapses the commit boundary the bug lived between and would pass without exercising it.
- R6. Payload coercion: numpy/pandas scalars and null sentinels coerce to JSON-native
  values, with no invalid `NaN` token and no non-serializable types.
- R7. Catalog column validation: requesting an unknown column, or one that collides with an
  alert column, fails loudly rather than silently corrupting the payload.
- R8. Ingest idempotency: re-delivering the same alert from the same broker creates no
  duplicate; each broker's delivery is recorded once.
- R9. Batch dispatch logic (tests existing behavior, not a new mechanism): a batch
  dispatches only on an existing threshold (`CROSSMATCH_BATCH_MAX_SIZE`, default 100000, or
  `CROSSMATCH_BATCH_MAX_WAIT_SECONDS`, default 900), and the existing stuck-`QUEUED`
  auto-recovery in `dispatch_crossmatch_batch` reverts to `INGESTED` after
  `CELERY_TASK_TIME_LIMIT * 2`.
- R12. Crossmatch/catalog-open errors fail loud: an exception opening or computing against a
  catalog propagates (or marks the affected alerts failed) rather than being swallowed into
  a zero-match. A test injects a raising mock at the catalog-open seam and asserts the
  failure surfaces, not silently absorbed.

**Automation and dependency safety**

- R10. The suite runs automatically on every change in CI, and a failing test blocks merge.
- R11. Transitive dependencies are pinned via a lockfile that is the single source of truth
  for **both** CI and the deployed image build, so the tested and running environments
  cannot diverge (the `hats` failure mode), with drift detection that fails loudly if the
  running environment's resolved dependencies diverge from the lock. A breaking minor of a
  transitive dependency cannot be silently resolved; upgrades are deliberate and reviewable.

## Acceptance Examples

- AE1. **Covers R4.** Given an alert at `MATCHED` whose single notification is `SENT`, when
  the dispatcher runs, then the alert becomes `NOTIFIED`. Given the same alert with its
  notification still `PENDING`, then it stays `MATCHED`.
- AE2. **Covers R5.** Given a notification whose alert is still `QUEUED` (the dispatcher
  fires mid-batch), when the batch later commits the alert to `MATCHED`, then the alert ends
  `NOTIFIED` — not stranded at `MATCHED`.
- AE3. **Covers R8.** Given the same alert delivered twice by the same broker, then exactly
  one alert row exists and the broker delivery is recorded once.
- AE4. **Covers R12.** Given a raising mock at the catalog-open seam, when a batch runs, then
  the error surfaces (propagates or marks the alerts failed) and the alerts are not left
  silently at zero matches.

## Scope Boundaries

- Deferred: deploy/startup smoke checks (open a catalog; one alert end-to-end) — a different
  mechanism (runtime/deploy probe) than the in-CI suite, revisit later.
- Deferred: broad coverage of the broker consumers, Flower, and deployment/infra — start
  with the crossmatch→notify core where the bugs clustered.
- Out: the gitops repo's `env-contract` CI guardrail — it already exists and is not
  duplicated here.

## Dependencies / Assumptions

- Tests run in-container or in a local venv against a Django test database, matching the
  existing in-container workflow in `docs/developer.md`.
- CI gating (R10) assumes a Postgres service available to the CI job; the app repo's current
  workflow only builds the image, so this adds a test job.
- The logic tests (R4–R9) assume Dask compute, the Kafka publish handler, and
  `lsdb.open_catalog` are mockable at clean seams — to be confirmed during planning.
- The dependency guard (R11) aligns with the existing
  `docs/solutions/conventions/dependency-pin-upgrade-pattern-2026-05-12.md`.

## Outstanding Questions

**Deferred to planning**

- Whether to add a class-level silent-failure guard (end-to-end alerts-in vs notified-out
  reconciliation, or a fail-loud runtime invariant) beyond the per-path tests — R4–R9/R12
  guard the known recurring instances, not the broader class the Problem Frame names.
- Lockfile mechanism for R11 (e.g., pip-compile/constraints vs uv) and how it composes with
  the existing version pins in `crossmatch/requirements.base.txt`.
- The exact mock/seam boundaries for Dask, Kafka, and HATS in R3 — where to cut so tests
  exercise real logic, not mock theater.
- Whether to fold `crossmatch/brokers/pittgoogle/tests.py` into the new pytest layout or
  leave it in place.
- CI job shape for R10 (Postgres service, Python/runtime matrix, where it sits relative to
  the build-image workflow).

## Sources / Research

- Bugs this work guards against (write-ups in the `crossmatch-service-k8s-gitops` repo):
  `docs/solutions/runtime-errors/lsdb-hats-original-schema-version-skew.md`,
  `docs/solutions/logic-errors/single-match-alerts-stuck-matched-notify-before-matched-race.md`,
  and the NOTIFIED pk-vs-natural-key fix (commit `e7e4886`, currently undocumented).
- Code under test: `crossmatch/tasks/crossmatch.py` (`crossmatch_batch`),
  `crossmatch/tasks/schedule.py` (`dispatch_notifications`), `crossmatch/brokers/__init__.py`
  (`ingest_alert`), `crossmatch/matching/catalog.py` and `crossmatch/matching/payload.py`.
- Existing test + workflow: `crossmatch/brokers/pittgoogle/tests.py`, the Testing section of
  `docs/developer.md`.
- Related app-repo conventions: `docs/solutions/conventions/dependency-pin-upgrade-pattern-2026-05-12.md`,
  `docs/solutions/design-patterns/coerce-numpy-pandas-scalars-to-json.md`.
