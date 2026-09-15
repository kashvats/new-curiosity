# Build Part 6 Report — Governance, Impact Memory & Operator Controls

**Date:** 2026-09-15

## Goal

Strengthen the Part 5 manual improvement system before considering any recurring autonomy. Part 6 adds project-specific governance, deterministic contract/invariant enforcement, repeat suppression, historical test/coverage impact memory, cancellation/discard controls, and operator surfaces in the dashboard and VS Code.

The safety boundary remains:

```text
observe / rank / select / experiment / verify / govern
        -> WAITING_APPROVAL -> explicit confirm=true -> govern again -> live apply
```

There is still no recurring scheduler.

## New backend modules

- `app/improvement_policy.py`
- `app/improvement_governance.py`
- `app/candidate_suppression.py`
- `app/improvement_test_impact.py`
- `tests/test_part6_governance.py`

## 1. Versioned project-specific policies

A project can persist multiple policy versions while exposing one active policy. A cycle snapshots the resolved policy at creation, preserving auditability if the active policy changes later.

Policy controls include:

- allowed risks,
- minimum candidate priority,
- allowed/blocked health categories,
- explicit protected API routes,
- protection of the active approved API baseline,
- required architecture paths,
- protected/forbidden paths,
- optional top-level architecture protection,
- maximum changed source-module line count,
- dependency-manifest edit permission,
- repeated-candidate suppression limits.

The human source-apply approval requirement is immutable and is always normalized to `true`.

## 2. Exact verified-patch governance

`improvement_governance.py` creates a temporary candidate workspace, applies the exact verified patch, captures the candidate API/architecture signature, and evaluates it against the cycle's policy snapshot.

A candidate can be blocked for:

- removing approved API routes that exist before the candidate,
- missing explicitly protected routes,
- modifying protected/forbidden paths,
- violating required-path invariants,
- introducing disallowed top-level source roots,
- exceeding configured changed-module line limits,
- changing dependency manifests when policy forbids it.

Governance runs twice:

1. after machine/reviewer/security/quality verification,
2. immediately before live apply.

This reduces time-of-check/time-of-use drift between verification and promotion.

## 3. Verified-candidate revocation

Part 6 closes a Part 5 loophole where non-winning experiment candidates remained independently `verified` in the shared repair store.

Now:

- governance-blocked repairs are marked `discarded`,
- non-winning verified experiments are marked `discarded`,
- user-discarded experiments revoke their verified repair,
- cancellation of a paused cycle revokes its selected verified repair,
- a verified repair created while cancellation is in flight is revoked when the repair returns.

The normal `apply_verified_repair()` path refuses discarded repairs.

## 4. Repeated-candidate suppression

Candidates receive a SHA-256 fingerprint derived from stable evidence:

```text
strategy_key + health category/code + risk + likely files
```

Prior attempted candidates with the same fingerprint are counted for the same project. When the active policy's repeat limit is reached, the candidate is persisted with:

- `suppressed=true`,
- `repeat_count`,
- `suppression_reason`.

Suppressed candidates remain inspectable but are not eligible for selection.

## 5. Test/check + coverage impact memory

Every improvement repair records:

- changed files,
- executed validation commands,
- per-check pass/fail state,
- overall validation result,
- quality score,
- available coverage/line/branch coverage signals.

When future candidates touch the same files, Part 6 retrieves prior impact records and can add historically relevant successful check commands to the candidate validation plan.

This memory is deterministic and local; it does not invent tests or coverage values.

## 6. Cancellation and experiment discard

New API controls:

```text
POST /improvements/cycles/{cycle_id}/cancel
POST /improvements/cycles/{cycle_id}/experiments/{experiment_id}/discard
```

Paused cycles cancel immediately. In-flight validation uses a cooperative cancel flag and stops after the current bounded repair call returns.

A currently selected winner in `WAITING_APPROVAL` cannot be discarded as an experiment; the user must cancel the cycle instead.

## 7. Governance/policy/impact API

```text
GET /improvements/policies/{project_name}
PUT /improvements/policies/{project_name}
GET /improvements/policies/{project_name}/history
GET /improvements/governance/checks
GET /improvements/test-impact
```

`/improvements/capabilities` now advertises the Part 6 governance features.

## 8. Database changes

New tables:

- `improvement_policies`
- `improvement_governance_checks`
- `improvement_test_impacts`

Expanded `improvement_cycles`:

- `policy_snapshot_json`
- `cancel_requested`
- `cancelled_at`

Expanded `improvement_candidates`:

- `candidate_fingerprint`
- `suppressed`
- `suppression_reason`
- `repeat_count`
- `impact_memory_json`

Expanded `improvement_experiments`:

- `discarded_at`

The migration remains additive/backward-compatible for existing SQLite databases.

## 9. Dashboard

New project-workspace tab:

```text
🧠 Improvements
```

It exposes:

- current health,
- recent cycles,
- manual/observe-only cycle creation,
- candidate selection,
- optional two-candidate experiment comparison,
- experiment discard,
- verified winner apply,
- cycle cancellation,
- approved baseline capture,
- governance result inspection,
- editable versioned project policy JSON.

The repository's frontend Dockerfile expected a `package.json` that was missing. Part 6 restores the React/Vite/Monaco package manifest. An npm install/build attempt exceeded the available local execution window, so frontend dependency installation is not claimed as a successful verification step.

## 10. VS Code extension 1.2.0

New commands:

```text
AI Coding Assistant: Improvement Center
AI Coding Assistant: Improve Project
AI Coding Assistant: Cancel Improvement Cycle
```

The manual flow uses the same backend cycle/event/selection/apply endpoints and preserves explicit approval.

## 11. Configuration

New settings:

```text
IMPROVEMENT_REPEAT_LIMIT=2
IMPROVEMENT_REPEAT_HISTORY_LIMIT=50
IMPROVEMENT_POLICY_MAX_REQUIRED_PATHS=100
IMPROVEMENT_POLICY_MAX_PROTECTED_ROUTES=200
IMPROVEMENT_GOVERNANCE_MAX_MODULE_LINES=1200
IMPROVEMENT_TEST_IMPACT_HISTORY_LIMIT=200
```

## Verification

Backend regression suite:

```text
58 passed
```

Compile/import validation:

```text
python -m compileall -q app tests
PASS

MODULES 91
IMPORT_FAILURES 0
```

OpenAPI smoke validation:

```text
Part 6 required routes present: true
OpenAPI path count: 93
```

VS Code extension:

```text
node --check extension.js
PASS

package.json parse
PASS
```

Frontend manifest:

```text
package.json parse
PASS
```

Part 6 touched backend modules through deterministic security review:

```text
Critical: 0
High:     0
Medium:   0
Low:      0
```

## Deliberately not added

Part 6 does **not** add:

- a cron/recurring improvement scheduler,
- autonomous live source promotion,
- a policy switch that disables human approval,
- network dependency-version guessing,
- automatic approval of API contract changes.

## Recommended Part 7

Build an eligibility/governance layer before scheduling: approval roles, immutable or signed policy snapshots, real coverage-report delta ingestion, failure-class cooldowns, cross-cycle regression attribution, and a deterministic guarded-autonomy eligibility report. Keep the scheduler disabled until those conditions are demonstrably satisfied.
