# Part 14 Production Release Governance Runbook

## Purpose

Use this runbook after Part 13 has produced a signed production release request for a `staging_validated` release. Part 14 governs authorization and produces a signed package for a separately operated production deployment system. It does not deploy production itself.

## 1. Configure operator identities

Configure distinct human operators in `IMPROVEMENT_OPERATOR_CREDENTIALS_JSON`. A practical minimum is:

```json
{
  "release.lead": {"role": "release-manager", "token": "..."},
  "operations.oncall": {"role": "ops", "token": "..."},
  "security.reviewer": {"role": "security", "token": "..."}
}
```

Store the JSON or individual secret material using the Part 11 secret-provider/deployment mechanism. Never commit real tokens.

## 2. Keep the release signing key available

Part 14 reuses `IMPROVEMENT_RELEASE_SIGNING_KEY` to sign governance locks and deployment packages. Keep it outside source control. Package generation should remain blocked if signatures are required and the signing key is unavailable.

## 3. Configure quorum

Default:

```env
IMPROVEMENT_PRODUCTION_GOVERNANCE_MIN_APPROVALS=2
IMPROVEMENT_PRODUCTION_GOVERNANCE_REQUIRED_ROLES=release-manager,ops
```

Approvers must be distinct operators. An approval applies only to the exact current governance digest.

## 4. Configure change-ticket rules

Default:

```env
IMPROVEMENT_PRODUCTION_GOVERNANCE_CHANGE_TICKET_REQUIRED=true
IMPROVEMENT_PRODUCTION_GOVERNANCE_CHANGE_TICKET_PATTERN=^[A-Z][A-Z0-9]+-[0-9]+$
```

Examples: `REL-140`, `OPS-812`, `JIRA-1234`.

## 5. Configure freeze windows

Absolute incident freeze example:

```json
[
  {
    "starts_at": "2026-09-15T12:00:00Z",
    "ends_at": "2026-09-15T16:00:00Z",
    "reason": "incident/change freeze"
  }
]
```

Recurring weekend example:

```json
[
  {
    "days": ["sat", "sun"],
    "start": "00:00",
    "end": "23:59",
    "timezone": "Asia/Kolkata",
    "reason": "weekend freeze"
  }
]
```

Set the JSON as `IMPROVEMENT_PRODUCTION_GOVERNANCE_FREEZE_WINDOWS_JSON`.

## 6. Optional release trains

Create a release train with a named production window. To require assignment:

```env
IMPROVEMENT_PRODUCTION_GOVERNANCE_RELEASE_TRAIN_REQUIRED=true
```

To require package generation during the train's active time window:

```env
IMPROVEMENT_PRODUCTION_GOVERNANCE_RELEASE_TRAIN_WINDOW_REQUIRED=true
```

Closing or freezing a train blocks a case assigned to it.

## 7. Governance workflow

1. Select the Part 13 production release request.
2. Create one governance case.
3. Attach the approved change ticket.
4. Generate a canary, blue-green, or rolling rollout plan.
5. Assign a release train when required.
6. Ask each required operator to approve the current digest independently.
7. Evaluate the case and resolve all blockers.
8. Have an authorized release manager create the immutable signed lock.
9. Have an authorized release manager/ops operator generate the signed deployer package.

If ticket/train/rollout inputs change before lock, all earlier approvals become stale and must be repeated.

## 8. Independent deployer verification

The independent production deployer should reject a package unless it can verify:

- the package digest/signature,
- the governance lock digest/signature,
- release/commit identity,
- change ticket,
- release window/train,
- quorum and required roles,
- rollout plan,
- artifact/provenance evidence referenced by the Part 13 request.

The deployer should obtain production credentials from its own secret system. Part 14 intentionally does not include them.

## 9. Incident/freeze behavior

A newly activated freeze can block package generation even when the governance case was already locked. Do not bypass this by editing the database or turning off signature requirements. Resolve the incident/freeze under your organization's normal release process.

## 10. Separation of duties

Recommended production topology:

```text
AI Coding Assistant backend
  - no production kubeconfig
  - no production AWS credentials
  - no production registry write credential
  - signs governance package only

Independent production deployer
  - verifies signatures/quorum
  - owns production credentials
  - executes approved rollout
  - records production deployment outcome separately
```

## 11. Verify a package before external deployment

Call:

```text
GET /improvements/production-governance/packages/{package_id}/verify
```

Require `valid=true`. A false result may indicate a package digest/signature mismatch, an invalidated governance lock, or a newly active freeze/release-train blocker. Treat any false result as a hard stop for the independent production deployer.
