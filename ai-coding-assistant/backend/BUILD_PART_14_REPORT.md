# Build Part 14 Report — Production Release Governance Plane

## Goal

Part 14 takes the signed, human-created Part 13 **production release request** and adds a dedicated production governance layer without adding production deployment authority to the AI backend. The result is a signed, immutable, credential-free package that an independently operated production deployer can verify and consume.

## State boundary

```text
Part 13 staging_validated
  -> signed production release request
  -> Part 14 governance case
  -> change ticket + rollout plan + optional release train
  -> evidence-bound multi-person approvals
  -> freeze/train/quorum evaluation
  -> immutable signed governance lock
  -> signed credential-free deployment package
  -> STOP
```

There is no production deployment state or executor in Part 14.

## New modules

- `app/improvement_production_governance_store.py` — governance case, approval, train, lock-event and package persistence.
- `app/improvement_production_governance.py` — policy evaluation, quorum, freeze windows, rollout plans, immutable lock and signed deployer package generation.
- `app/improvement_production_governance_api.py` — authenticated production-governance API surface.

## Persistence

New additive tables:

- `improvement_production_governance_cases`
- `improvement_production_governance_approvals`
- `improvement_release_trains`
- `improvement_production_deployment_packages`
- `improvement_production_governance_events`

A unique case is maintained for each Part 13 production release request. A single immutable deployment package is generated per locked case.

## Evidence-bound approvals

Every approval is stored with the current canonical governance digest. The digest binds:

- Part 13 production request ID and signed release-evidence digest,
- release/commit identity,
- change ticket,
- release train definition,
- rollout plan.

Changing any of those inputs changes the digest. Previous approvals remain auditable but become stale and no longer count toward quorum.

Default quorum:

```text
minimum distinct approvals = 2
required roles = release-manager, ops
```

Operator identity uses the existing Part 9 operator registry. Tokens are verified in memory and are not stored in governance records.

## Change tickets and release trains

Change references are validated against a configurable regular expression. The default accepts Jira-style values such as `REL-140`.

Release trains are production-window metadata only. They contain an open/frozen/closed state plus start/end times and timezone. Projects may require a release train and may optionally require package generation to occur inside its time window.

## Freeze windows

`IMPROVEMENT_PRODUCTION_GOVERNANCE_FREEZE_WINDOWS_JSON` supports absolute or recurring freeze windows. An active freeze blocks governance readiness and is checked again before signed deployment-package generation, so a newly activated incident/change freeze cannot be bypassed by an earlier lock.

## Rollout plans

Part 14 generates declarative plans for:

- canary,
- blue-green,
- rolling rollout.

Plans contain observation stages and rollback triggers but are never executed by the backend.

## Immutable lock

After quorum and governance gates pass, an authorized release manager creates the lock using explicit `confirm=true`. The current governance digest is signed with the Part 12/13 release signing key. After `locked_at` is set, ticket, rollout and train inputs cannot be changed.

Package generation recomputes the digest and verifies the lock signature before continuing.

## Independent deployer package

The final package contains release/commit identity, the signed Part 13 request reference, ticket, release train, rollout plan, counted approvals and the governance lock. It explicitly states:

```text
production_credentials_included = false
backend_can_execute_production = false
automatic_execution_authorized = false
independent_deployer_must_verify_signature = true
```

The complete package is canonically hashed and HMAC-signed. No production access key, kubeconfig, AWS credentials, registry password or deployment token is collected or persisted.

## UI

The dashboard Improvements workspace adds a Part 14 Production Release Governance card for opening cases, setting ticket/rollout evidence, approvals, locking and package generation.

VS Code extension version **1.10.0** adds **Production Release Governance** with the same guarded workflow. It does not add a production deployment command.

## Regression

Part 14 adds `tests/test_part14_production_governance.py` covering schema/capabilities, signed-request integrity, quorum, stale approvals, duplicate approvals, freeze controls, release trains, immutable locks, role authorization, signed credential-free packages and route-boundary checks.

## Safety invariant

```text
AI/backend may prepare governance evidence and package
                         ↓
             independent production deployer
```

The Part 14 backend contains no production deployment executor and the API contains no `production-deploy`, `deploy-production`, `execute-production`, or `promote-production` route.

## Package verification

Independent deployers can call `GET /improvements/production-governance/packages/{package_id}/verify` before acting. The verifier recomputes the canonical package digest, checks its signature, re-verifies the immutable governance lock, and reports current freeze/release-train blockers. It never executes a deployment.

## Final validation

- Backend regression set: **145 passed** (65 Part 10–14/foundation tests + 80 Part 2–9 tests; both complete groups pass).
- Part 14 regression suite: **12 passed**.
- Backend module import sweep: **123 modules, 0 failures**.
- FastAPI/OpenAPI route audit: **176 unique paths**.
- Part 14 production-governance paths: **17**.
- Production deploy/promote/execute routes: **0**.
- Deterministic security gate for Part 14 control modules: **0 critical / 0 high / 0 medium / 0 low**.
- VS Code extension syntax/manifest: pass, version **1.10.0**.
- Docker Compose YAML: pass.
- Frontend package manifest: pass. The production Vite build was not verified in this environment because `node_modules` is not present (`vite: not found`).
