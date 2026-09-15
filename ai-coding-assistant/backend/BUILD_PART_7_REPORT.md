# Build Part 7 Report — Autonomy Readiness, Approval Identity & Regression Evidence

**Date:** 2026-09-15

## Goal

Part 7 adds the evidence and control plane required before any recurring autonomy can be considered. It deliberately **does not add a scheduler** and does not relax the existing explicit source-apply confirmation, exact-patch governance, snapshot, verification, or rollback boundaries.

The new question is deterministic:

```text
Is this project safe to automate under the configured evidence gates?
```

The answer is exposed as either `safe_to_automate` or `not_safe_to_automate`, with every failed gate listed.

## New backend modules

- `app/improvement_integrity.py`
- `app/improvement_approvals.py`
- `app/improvement_coverage.py`
- `app/improvement_risk_controls.py`
- `app/improvement_regression_attribution.py`
- `app/autonomy_readiness.py`
- `tests/test_part7_autonomy_readiness.py`

## 1. Tamper-evident / signed policy snapshots

Every improvement cycle now receives a resolved policy snapshot at creation and stores a canonical integrity envelope.

- Without a signing key: SHA-256 digest detects accidental/casual mutation.
- With `IMPROVEMENT_POLICY_SIGNING_KEY`: the digest is HMAC-SHA256 signed.
- Integrity is checked during the cycle and again immediately before apply.
- A mismatch stops promotion in `POLICY_INTEGRITY_BLOCKED`.

The signing key itself is never stored in SQLite.

## 2. Authenticated approval-role evidence

Part 7 adds an optional local approver credential registry configured through:

```text
IMPROVEMENT_APPROVER_CREDENTIALS_JSON
```

Example:

```json
{
  "alice": {"role": "maintainer", "token": "replace-with-secret"},
  "security-reviewer": {"role": "security", "token": "replace-with-secret"}
}
```

Project policy can require:

```json
{
  "approval": {
    "human_source_apply_required": true,
    "min_verified_approvals": 1,
    "required_roles": ["maintainer"],
    "distinct_roles": false
  }
}
```

Tokens are compared in constant time and are **not persisted**. Only approver id/hash, role, verified state, cycle and timestamp are stored.

New API:

```text
POST /improvements/cycles/{cycle_id}/approve
GET  /improvements/cycles/{cycle_id}/approvals
```

If the snapshotted policy requires a verified quorum and it is not satisfied, apply is stopped in `APPROVAL_BLOCKED`.

The original explicit `confirm=true` requirement remains in addition to approval evidence.

## 3. Real coverage-report ingestion

Part 6 remembered coverage values if they happened to appear in validation results. Part 7 adds explicit coverage evidence ingestion.

Supported normalized inputs:

- coverage.py JSON totals,
- generic JSON coverage totals,
- Cobertura XML (`line-rate`, `branch-rate`).

APIs:

```text
POST /improvements/coverage/reports
GET  /improvements/coverage/reports
GET  /improvements/coverage/delta
```

Reports persist line/branch coverage and can be attached to a cycle/phase (`baseline`, `pre_apply`, `post_apply`, `current`, `final`). Delta calculation never invents coverage when either side is missing.

## 4. Failure-class cooldowns

Repeated-candidate suppression remains in place. Part 7 additionally applies time-based cooldowns after recent failures with separate windows for:

- validation failure,
- governance failure,
- cycle budget failure,
- rollback / health regression.

A candidate in active cooldown remains visible but is not policy-eligible.

## 5. Historical risk escalation

Candidate risk can now be raised conservatively when the same deterministic candidate fingerprint has accumulated enough failed history. The record preserves:

- base risk,
- effective risk,
- failure sample count,
- severe failure count,
- whether escalation occurred.

This means a historically troublesome candidate cannot keep entering the pipeline under its original lower-risk label.

## 6. Cross-cycle regression attribution

Measured applies now persist deterministic attribution records containing:

- dimension deltas,
- regressed dimensions,
- improved dimensions,
- changed files,
- apply status,
- failure class,
- confidence level.

API:

```text
GET /improvements/regressions
```

Health-regression rollbacks are explicitly classified, and successful applies can still record a negative dimension delta even if the weighted overall health threshold did not trigger rollback.

## 7. Guarded-autonomy readiness report

```text
GET /improvements/readiness?project_name=...
```

The report checks deterministic gates including:

- explicit active project policy,
- configured HMAC policy signing,
- authenticated approver registry + required approval quorum,
- active approved project baseline,
- persisted project health above threshold with no high/critical findings,
- no drift from approved API/architecture baseline,
- ingested line-coverage evidence above threshold,
- dependency-health score,
- minimum successful measured manual cycles,
- maximum rollback rate,
- no recent attributed regressions/rollbacks,
- no recent governance-blocked checks.

Result:

```json
{
  "verdict": "safe_to_automate | not_safe_to_automate",
  "eligible": false,
  "scheduler_enabled": false,
  "automatic_source_apply_enabled": false,
  "gates": [],
  "blockers": []
}
```

A `safe_to_automate` result is evidence for a **future guarded scheduler decision**. It does not enable recurrence or automatic source promotion.

## 8. Persistence changes

New tables:

- `improvement_approvals`
- `improvement_coverage_reports`
- `improvement_regression_attributions`

Expanded `improvement_cycles`:

- `policy_integrity_json`

Expanded `improvement_candidates`:

- `base_risk`
- `cooldown_until`
- `cooldown_reason`
- `risk_escalation_json`

All migrations remain additive for existing SQLite databases.

## 9. Dashboard

The project Improvement Center now surfaces:

- autonomy-readiness verdict and blockers,
- policy/health/cycle state,
- candidate cooldowns and risk escalation,
- authenticated approval entry when the snapshotted policy requires a quorum,
- the existing selection/experiment/governance/apply/cancel controls.

The approval token input is password-masked and is not stored by the backend.

## 10. VS Code extension 1.3.0

New command:

```text
AI Coding Assistant: Autonomy Readiness
```

The Improvement Center also displays readiness evidence. When a cycle requires verified role approval, the manual flow prompts for approver id, role and a password-masked token before source apply is offered.

## 11. Configuration

New important settings:

```text
IMPROVEMENT_POLICY_SIGNING_KEY=
IMPROVEMENT_APPROVER_CREDENTIALS_JSON={}
IMPROVEMENT_COOLDOWN_VALIDATION_HOURS=2
IMPROVEMENT_COOLDOWN_GOVERNANCE_HOURS=12
IMPROVEMENT_COOLDOWN_BUDGET_HOURS=1
IMPROVEMENT_COOLDOWN_ROLLBACK_HOURS=24
IMPROVEMENT_RISK_ESCALATION_FAILURES=2
IMPROVEMENT_READINESS_MIN_HEALTH=85
IMPROVEMENT_READINESS_MIN_COVERAGE=70
IMPROVEMENT_READINESS_MIN_DEPENDENCY_SCORE=85
IMPROVEMENT_READINESS_MIN_SUCCESSFUL_CYCLES=3
IMPROVEMENT_READINESS_MAX_ROLLBACK_RATE=0.10
IMPROVEMENT_READINESS_LOOKBACK=20
IMPROVEMENT_COVERAGE_MAX_REPORT_BYTES=2000000
```

Docker Compose passes the policy-signing key and approver registry from the root environment into the backend container.

## Verification

Backend regression suite:

```text
67 passed
```

Part 7 test coverage includes:

- additive schema migration,
- HMAC snapshot sealing,
- policy tamper detection,
- authenticated role approval and token non-persistence,
- coverage.py JSON ingestion,
- Cobertura XML ingestion,
- coverage delta calculation,
- failure cooldown,
- risk escalation,
- regression attribution,
- negative readiness report,
- fully satisfied readiness report,
- pre-apply policy-integrity blocking,
- API route registration.

## Deliberately not added

Part 7 does **not** add:

- cron/recurring improvement scheduling,
- unattended candidate selection,
- automatic approval,
- automatic source promotion,
- a policy option to bypass human confirmation,
- remote identity-provider integration,
- automatic dependency version guessing.

## Recommended Part 8

If the project repeatedly reaches `safe_to_automate`, the next layer should be a **dry-run guarded scheduler/control plane**, not autonomous source apply: observe/propose-only schedules, maintenance windows, global/project rate limits, emergency kill switch, concurrency leases, CI/webhook evidence ingestion, SLO/error-budget gates, and canary scheduling. Live promotion should remain explicitly approved until that control plane has substantial evidence.
