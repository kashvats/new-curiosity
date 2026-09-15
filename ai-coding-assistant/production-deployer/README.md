# Independent Production Deployer — Part 15

This service is a separate production trust boundary. It consumes the signed, credential-free Part 14 deployment package plus a short-lived Part 15 authorization issued by the AI backend. It is intentionally not part of the AI backend process and must not mount the AI workspace or source tree.

## Safety model

- Production execution is **disabled by default** (`PRODUCTION_DEPLOYER_EXECUTION_ENABLED=false`).
- The request body may not contain passwords, access keys, tokens, kubeconfig, private keys, or other credential-like fields.
- Production credentials belong to this deployer runtime only, preferably through workload identity or files mounted under `/run/production-deployer-secrets`.
- The deployer verifies the Part 14 package HMAC, immutable governance lock, approval quorum, required roles, artifact binding, short-lived authorization HMAC, exact package digest, expiry, audience, and single-use authorization.
- Kubernetes/ECS direct execution is limited to the exact bound artifact. Generic canary and blue/green traffic manipulation is not guessed; those strategies use externally reported stages plus SLO gates.
- Every terminal deployment emits a signed receipt. The AI backend can ingest that receipt and use it as production outcome evidence for future improvement ranking/risk.

## Run locally without production execution

```bash
cp .env.example .env
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8015
```

Or from the repository root:

```bash
docker compose --profile production-deployer up -d production-deployer
```

The Compose profile does **not** mount the backend workspace into this service and enables no production credentials by default.

## Required cryptographic relationship

`PRODUCTION_DEPLOYER_PACKAGE_SIGNING_KEY` must independently receive the same signing material used to verify the signed governance package/authorization. `PRODUCTION_DEPLOYER_RECEIPT_SIGNING_KEY` should be a separate deployer-owned key; configure the matching value as `IMPROVEMENT_PRODUCTION_OUTCOME_SIGNING_KEY` on the AI backend so signed receipts can be learned from.

Do not expose either value through the API.

## API

- `GET /health/live`
- `GET /health/ready`
- `GET /capabilities`
- `POST /packages/verify`
- `POST /deployments`
- `GET /deployments`
- `GET /deployments/{id}`
- `POST /deployments/{id}/execute`
- `POST /deployments/{id}/observations`
- `POST /deployments/{id}/stages/advance`
- `POST /deployments/{id}/rollback`
- `POST /deployments/{id}/abort`
- `GET /deployments/{id}/receipt`

Mutating deployment endpoints require `X-Production-Operator-ID` and `X-Production-Operator-Token` when the operator registry is configured.

## Part 16 hardening

Part 16 adds verification-only key rotation, SLO-window evaluation, hash-chained deployment audit events, migration-safety checks, non-destructive rollback drills, safe chaos simulations, and concurrency/load smoke tooling. See `../generated_docs/PART16_PRODUCTION_CERTIFICATION_RUNBOOK.md`.
