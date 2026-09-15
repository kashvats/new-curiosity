# Part 16 Production Readiness Certification Runbook

Part 16 is the final hardening/certification phase before the architecture is considered v1.0-ready. It does not add deployment authority to the AI backend.

## Required evidence gates

The default certificate requires fresh evidence for: `deployer_tests`, `migration_safety`, `key_rotation`, `slo_window`, `rollback_drill`, `chaos_failover`, `security_attack`, `audit_chain`, and `load_concurrency`.

Evidence is recorded through `POST /improvements/certification/evidence` and is bound to the authenticated control-plane operator when the operator registry is configured. A readiness report is available at `GET /improvements/certification/readiness?project_name=...`.

## Independent deployer checks

The deployer exposes non-destructive hardening endpoints:

- `GET /hardening/migration-safety`
- `GET /hardening/concurrency`
- `POST /hardening/chaos/simulate`
- `GET /deployments/{id}/audit-chain`
- `POST /deployments/{id}/slo-window`
- `GET /deployments/{id}/rollback-drill`

The rollback drill checks that a reversible previous state is available; it does not issue a production rollback command.

## Signing-key rotation

During rotation, configure the new active key and temporarily retain the previous verification key(s):

- `PRODUCTION_DEPLOYER_PREVIOUS_PACKAGE_SIGNING_KEYS`
- `PRODUCTION_DEPLOYER_PREVIOUS_RECEIPT_SIGNING_KEYS`
- `IMPROVEMENT_PRODUCTION_OUTCOME_PREVIOUS_SIGNING_KEYS`

New signatures are always created with the active key. Previous keys are verification-only and should be removed after the maximum package/authorization/receipt lifetime has elapsed.

## SLO-window gate

Part 15 evaluated individual observations. Part 16 can evaluate a sequence of observations and requires both a minimum sample count and a configured pass ratio. This avoids declaring a rollout healthy from a single transient sample.

## Audit-chain verification

New production deployer events are chained with SHA-256 using the prior event hash. `GET /deployments/{id}/audit-chain` recomputes the chain and reports any altered event payload/hash linkage.

## Certification

Set a dedicated `IMPROVEMENT_CERTIFICATION_SIGNING_KEY`. When every required evidence gate is fresh and passing, an authorized operator can issue a certificate with `POST /improvements/certification/certificates` and `confirm=true`.

The resulting certificate is HMAC-SHA256 signed and can be checked with `GET /improvements/certification/certificates/{id}/verify`.

A certificate is an operational readiness assertion. It does not create production credentials, bypass Part 14 governance, or authorize the AI backend to deploy production.
