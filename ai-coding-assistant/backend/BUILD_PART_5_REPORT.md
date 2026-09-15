# Build Part 5 Report — Outcome Learning, Controlled Experiments & Drift Guards

**Date:** 2026-09-15

## Goal

Make the Part 4 improvement controller learn from measured outcomes and support bounded experimentation **without** enabling a recurring scheduler or unattended live-project writes.

Part 5 keeps the same safety boundary:

```text
observe / rank / experiment / verify -> WAITING_APPROVAL -> explicit confirm=true -> live apply
```

No policy in Part 5 can self-start a recurring cycle or bypass human approval for source promotion.

## New modules

- `app/improvement_learning.py`
- `app/improvement_budget.py`
- `app/dependency_health.py`
- `app/project_baselines.py`
- `tests/test_part5_learning_experiments.py`

## Major improvements

### 1. Outcome-aware strategy learning

Every generated improvement candidate now carries a deterministic `strategy_key` derived from:

```text
health category : finding code : risk
```

Examples:

```text
knowledge:missing_readme:low
tests:machine_checks_failing:medium
security:hardcoded_secret:high
```

Measured outcomes are aggregated across previous cycles using:

- sample count,
- success count,
- rollback count,
- success rate,
- average health-score delta.

Candidate priority is adjusted only after a minimum history threshold is reached. Part 5 uses conservative Bayesian smoothing so a single lucky or failed cycle cannot strongly distort ranking.

The original deterministic score is retained as `base_priority_score`; learned ranking is recorded separately through:

- `learning_multiplier`,
- `history_samples`,
- `history_success_rate`,
- `history_average_score_delta`,
- final `priority_score`.

### 2. Manual candidate-selection boundary

A manual cycle may now set:

```json
{
  "pause_for_candidate_selection": true
}
```

The cycle stops at:

```text
WAITING_SELECTION
```

At this point no repair LLM call has run and no candidate workspace has been created. The user can inspect all ranked candidates and explicitly choose the one to validate.

Selection API:

```text
POST /improvements/cycles/{cycle_id}/select
```

The selected candidate must still satisfy the cycle's risk and minimum-priority policy.

### 3. Controlled isolated experiment mode

Part 5 can compare several eligible candidates in separate candidate workspaces before choosing a verified winner.

Request controls:

```json
{
  "experiment_mode": true,
  "experiment_candidates": 2
}
```

Experiment behavior:

1. each candidate runs through the existing `repair_issue()` loop independently,
2. each candidate receives machine validation + reviewer + security + quality gates,
3. experiment summaries are persisted,
4. only verified candidates are eligible to win,
5. winner selection prefers verified quality score, then learned candidate priority,
6. the winning repair still stops at `WAITING_APPROVAL`.

No experiment edits the live source tree.

### 4. Cycle-level resource budgets

Part 5 adds bounded budgets above the existing patch/command safety limits.

Tracked resources:

- candidate repair runs,
- repair attempts,
- cumulative changed files,
- cumulative candidate patch bytes.

Default hard ceilings:

```text
IMPROVEMENT_MAX_CYCLE_REPAIRS=3
IMPROVEMENT_MAX_CYCLE_ATTEMPTS=8
IMPROVEMENT_MAX_CYCLE_CHANGED_FILES=16
IMPROVEMENT_MAX_CYCLE_PATCH_BYTES=600000
```

A request may choose smaller values but cannot increase beyond server configuration.

If a cycle exhausts a budget it enters:

```text
BUDGET_EXCEEDED
```

and cannot continue to apply.

### 5. API-contract + architecture drift baselines

`project_baselines.py` captures a deterministic approved baseline containing:

- discovered FastAPI-style HTTP route signatures,
- bounded source-file layout,
- top-level source distribution,
- API hash,
- architecture-layout hash.

Drift detection reports:

- removed API routes,
- added API routes,
- removed source files,
- added source files,
- source-layout similarity.

Removed API contract entries are treated as strong regression evidence, but drift findings are intentionally **review-only** by default rather than automatically reverted.

New API:

```text
POST /improvements/baselines
GET  /improvements/baselines
GET  /improvements/drift
```

### 6. Offline dependency-health intelligence

`dependency_health.py` inspects local manifests without contacting package registries.

It currently detects:

- non-exact Python requirement declarations,
- conflicting exact Python pins,
- invalid `package.json`,
- unbounded Node versions such as `latest` or `*`,
- Node dependency declarations without a recognized lockfile.

Reproducibility findings that require version selection or lockfile generation are deliberately review-only by default. Part 5 does **not** fabricate dependency versions and does not use network package metadata.

New API:

```text
GET /improvements/dependencies
```

### 7. Expanded deterministic project-health model

Project health now includes two additional dimensions:

- `dependencies`,
- `drift`.

The full score now combines:

- tests,
- security,
- architecture,
- quality,
- knowledge,
- dependencies,
- drift.

Tests and security remain the dominant weighted signals.

### 8. Experiment persistence

New persisted records capture each isolated experiment:

```text
improvement_experiments
```

Each row records:

- cycle ID,
- candidate ID,
- repair issue ID,
- experiment rank,
- verification status,
- quality score,
- resource usage,
- bounded result summary.

Experiment API:

```text
GET /improvements/cycles/{cycle_id}/experiments
```

### 9. Learning inspection API

Strategy performance can be inspected directly:

```text
GET /improvements/learning/strategies
```

This exposes measured history rather than hidden model preference.

## Database changes

New tables:

- `improvement_experiments`
- `project_baselines`

Expanded `improvement_cycles`:

- `budget_json`
- `usage_json`

Expanded `improvement_candidates`:

- `strategy_key`
- `base_priority_score`
- `learning_multiplier`
- `history_samples`
- `history_success_rate`
- `history_average_score_delta`

Migrations remain backward-compatible with Part 1–4 SQLite databases.

## New / expanded HTTP API

```text
GET  /improvements/capabilities
GET  /improvements/health
GET  /improvements/dependencies

POST /improvements/baselines
GET  /improvements/baselines
GET  /improvements/drift

GET  /improvements/learning/strategies

POST /improvements/cycles
GET  /improvements/cycles
GET  /improvements/cycles/{cycle_id}
POST /improvements/cycles/{cycle_id}/select
GET  /improvements/cycles/{cycle_id}/experiments
GET  /improvements/cycles/{cycle_id}/events
GET  /improvements/cycles/{cycle_id}/events/stream
POST /improvements/cycles/{cycle_id}/apply

GET  /improvements/outcomes
```

## State-machine extension

Part 5 adds an optional manual-selection pause:

```text
IDLE
  -> OBSERVING
  -> DIAGNOSING
  -> PROPOSING
  -> WAITING_SELECTION     (optional)
  -> VALIDATING
  -> WAITING_APPROVAL
  -> APPLYING
  -> MONITORING
  -> LEARNING
  -> IDLE
```

Failure/stop states remain:

- `VALIDATION_FAILED`
- `BLOCKED_BY_CAPABILITY`
- `BUDGET_EXCEEDED`
- `ROLLBACK_REQUIRED`

## Safety boundaries retained / strengthened

- no recurring scheduler,
- no unattended source promotion,
- no live-project edits during experiments,
- every experiment uses an isolated candidate workspace,
- exact verified-candidate promotion only,
- stale-hash and protected-path controls remain active,
- machine checks remain mandatory,
- Reviewer/Security/Quality gates remain mandatory,
- explicit `confirm=true` remains mandatory for apply,
- health-regression rollback remains active,
- dependency analysis uses no network registry lookups,
- API/architecture drift does not auto-revert intentional changes,
- user-selected candidates must still satisfy policy,
- cycle compute/change budgets can only be tightened by clients, not raised beyond server ceilings.

## Configuration added

```text
IMPROVEMENT_MIN_LEARNING_SAMPLES=3
IMPROVEMENT_HISTORY_LIMIT=200
IMPROVEMENT_EXPERIMENT_MAX_CANDIDATES=3
IMPROVEMENT_MAX_CYCLE_REPAIRS=3
IMPROVEMENT_MAX_CYCLE_ATTEMPTS=8
IMPROVEMENT_MAX_CYCLE_CHANGED_FILES=16
IMPROVEMENT_MAX_CYCLE_PATCH_BYTES=600000
```

## Verification

Commands executed:

```bash
python -m compileall -q app tests
pytest -q
```

Result:

```text
49 passed
```

Backend import smoke test:

```text
MODULES 87
IMPORT_FAILURES 0
```

VS Code extension validation:

```text
node --check extension.js
PASS

package.json JSON parse
PASS
```

Part 5 tests cover:

- backward-compatible schema creation,
- dependency-health findings,
- API-contract baseline removal/addition detection,
- conservative strategy re-ranking after measured history,
- `WAITING_SELECTION` behavior,
- explicit candidate override and resume,
- isolated two-candidate experiment selection,
- experiment persistence,
- cycle-attempt budget exhaustion,
- new API route registration.

## Deliberately deferred to Part 6

Part 6 should strengthen decision quality and operational control before any recurring scheduler is considered:

- protected API-contract policies with intentional-change approvals,
- test-impact and coverage-delta memory per strategy,
- semantic architecture invariants beyond file layout,
- duplicate/redundant candidate suppression across cycles,
- experiment cancellation and explicit discard endpoints,
- project-specific improvement policies,
- dashboard/VS Code UI for health, candidates, experiments and outcomes,
- guarded policy eligibility based on sufficient successful manual history,
- recurring scheduler remains last.
