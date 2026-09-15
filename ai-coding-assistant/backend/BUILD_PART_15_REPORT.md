# Part 15 Build Report — Independent Production Deployer + Production Outcome Learning

## Objective

Part 15 completes the production trust-boundary design started in Part 14. The AI backend remains a governance/authorization system with no production credentials or production execution adapter. A new, separately deployable service consumes a signed package plus a short-lived single-use authorization, performs tightly controlled production rollout actions, emits signed receipts, and feeds those outcomes back into future improvement ranking.

## Production learning

The system **does learn from past mistakes**, but this is deliberately operational memory rather than model-weight training. Signed production deployment outcomes are persisted and linked back to the candidate strategy that produced the release. Future candidates with the same strategy are adjusted using production success/failure/rollback history. Rollbacks receive the strongest penalty, repeated production failures escalate candidate risk, and the evidence is visible through `/improvements/production-outcomes/learning`.

The loop is:

`candidate -> verification -> staging -> governance -> independent deployer -> signed receipt -> outcome memory -> future ranking/risk`

## Backend additions

- exact immutable production artifact binding on governance cases
- short-lived signed deployment authorization bound to package digest and artifact digest
- additive production authorization/outcome schema
- signed receipt ingestion with replay protection
- production strategy statistics
- learning multiplier integrated into Part 5 ranking
- production failure/rollback evidence integrated into Part 7 risk escalation
- production-learning APIs and UI/VS Code visibility

## Independent production deployer

A new `production-deployer/` service has its own FastAPI app, SQLite state, operator registry, execution enable flag, package-verification key, receipt-signing key, production credentials/runtime identity, deployment observations, events, and receipts. It does not mount the AI backend source/workspace.

Direct generic rolling execution is implemented for Kubernetes and ECS only when explicitly enabled. Canary and blue/green strategies use externally executed stages with SLO evidence because safe traffic shifting is platform-specific and must not be guessed.

## Safety invariants

- AI backend cannot execute production.
- Production deployer execution defaults off.
- Production credentials are rejected from API payloads.
- Authorization is short-lived and single-use.
- Artifact reference and SHA-256 are exact-bound.
- Signed governance/package/authorization evidence is verified before execution.
- Health/SLO regression halts rollout; rollback is automatic when configured.
- Terminal receipts are HMAC signed and replay protected by the backend.
- Operational learning does not fine-tune or retrain the LLM.

## Validation

- Backend test inventory: **152 tests**; a complete Part 15 regression run reported **152 passed** after backend implementation. The pre-existing combined pytest process can linger after reporting completion because of runtime/background infrastructure, so targeted critical regression groups were also run independently.
- Part 15 backend tests: **7 passed**.
- Production deployer tests: **8 passed**.
- Learning/governance compatibility group (Parts 5, 7, 14, 15): **36 passed**.
- Backend modules: **125**, import failures: **0**.
- Production deployer modules: **6**, import failures: **0**.
- Backend OpenAPI paths: **179**; Part 15 backend paths: **7**; forbidden production-execution paths in AI backend: **0**.
- Independent deployer OpenAPI paths: **12**.
- Deterministic security review of Part 15 control/deployer modules: **0 critical, 0 high, 0 medium, 0 low**.
- VS Code extension JavaScript and JSON manifest validation: passed.
- Docker Compose profile/volume parsing: passed.

The frontend manifest and JSX integration are included, but the archive intentionally contains no `node_modules`; a production Vite build is not claimed in this build report.
