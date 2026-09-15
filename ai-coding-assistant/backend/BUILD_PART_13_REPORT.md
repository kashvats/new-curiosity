# Build Part 13 Report — Staging Providers & Production Release Handoff

## Goal

Part 13 extends the Part 12 isolated release candidate into a real **staging-only** delivery flow. It can coordinate CI, staging OCI promotion, staging deployment, staging validation, provenance and rollback, then emit a human-authorized **production release request**. It deliberately contains no production deployment implementation.

## State boundary

```text
verified repair
  -> isolated Part 12 release pipeline
  -> staging_ready
  -> staging deployment
  -> staging smoke/API/E2E checks
  -> SLSA-style provenance
  -> staging_validated
  -> explicit production-release-request
  -> STOP
```

A production release request is evidence and audit state only. `production_deployment_supported=false` is reported by Part 13 capabilities and responses.

## New modules

- `app/improvement_staging_store.py` — staging deployment, attestation and release-request persistence.
- `app/improvement_staging_providers.py` — GitHub Actions, GitLab Pipeline, Kubernetes, ECS and staging OCI adapters.
- `app/improvement_staging_security.py` — SLSA/in-toto provenance and optional Cosign attestation.
- `app/improvement_staging_orchestrator.py` — staging state machine, tests, rollback and production-request handoff.
- `app/improvement_staging_api.py` — authenticated Part 13 API surface.

## Persistence

New additive tables:

- `improvement_staging_deployments`
- `improvement_release_attestations`
- `improvement_production_release_requests`

Production requests have no executable deployment fields or worker states.

## Staging provider safety

External execution and automatic preview teardown are disabled by default:

```env
IMPROVEMENT_STAGING_EXECUTION_ENABLED=false
IMPROVEMENT_STAGING_CI_TRIGGER_ENABLED=false
IMPROVEMENT_STAGING_OCI_EXECUTION_ENABLED=false
IMPROVEMENT_RELEASE_COSIGN_ENABLED=false
IMPROVEMENT_STAGING_AUTO_TEARDOWN_EXPIRED=false
```

Kubernetes and ECS target identifiers are checked for production-like tokens (`prod`, `production` by default). OCI staging destinations receive the same deny-token guard. External staging previews require HTTPS except localhost development URLs.

When Kubernetes execution is enabled, the adapter invokes fixed `kubectl apply/delete` arguments with `shell=False`. ECS uses fixed `aws ecs update-service` arguments. OCI promotion uses fixed `docker pull/tag/push` arguments. These tools are not automatically installed in the normal backend image; use a dedicated staging runner for enabled execution.

## CI adapters

Part 13 can prepare or trigger:

- GitHub Actions workflow dispatches
- GitLab pipelines

Triggering is opt-in. When disabled, a deterministic `planned` result is recorded without a network side effect. Tokens resolve through the Part 11 secret-provider abstraction.

## Staging validation

Staging tests are fixed-array commands routed through the existing `safe_commands` policy. Allowed check kinds are:

- `smoke`
- `api`
- `e2e`

A staging deployment must be `ready` before tests run. All requested checks must pass before the release becomes `staging_validated`.

## Provenance and attestations

Part 13 emits an in-toto Statement v1 with SLSA provenance v1 predicate information. The statement binds the Part 12 artifacts/digests, release ID, project, verified issue, commit SHA and builder metadata. Its canonical SHA-256 digest is signed with the existing release HMAC key when configured.

Optional Cosign support invokes `cosign attest --type slsaprovenance` with fixed arguments and is disabled by default.

## Production release request

Creating `/production-release-request` requires:

1. release status `staging_validated`,
2. at least one validated staging deployment,
3. SLSA provenance,
4. `confirm=true`,
5. a **verified operator identity** by default,
6. an allowed operator role (`release-manager,maintainer` by default).

It records a digest of release evidence + staging deployment evidence + attestations and signs that digest with the configured release signing key. It does not run a deployment and responds with `production_deployment_executed=false`.

## UI

The dashboard identifies the Part 13 staging-provider boundary and can register an external staging deployment or create a production release request for a validated release.

VS Code extension version **1.9.0** adds **Staging Provider & Release Handoff** for inspecting Part 13 capabilities, registering external staging deployments and creating human-authorized release requests.

## Regression

Part 13 adds `tests/test_part13_staging_providers.py` with coverage for schema, production-target denial, staging adapters, safe tests, SLSA, optional Cosign, rollback/preview teardown, operator/role handoff authorization and API boundary checks.

Final verification is recorded in the handoff response and should be re-run with `pytest -q` after deployment-environment dependency changes.

## Final validation

- Full backend regression suite: **133 passed**.
- Part 13 regression suite: **12 passed**.
- Backend module import sweep: **120 modules, 0 failures**.
- OpenAPI: **155 unique paths**, with all Part 13 staging paths registered.
- Explicit production deployment/promote routes: **0**.
- Deterministic security gate for Part 13 control modules: **0 critical / 0 high / 0 medium / 0 low**.
- VS Code extension syntax/manifest: pass, version **1.9.0**.
- Docker Compose YAML: pass.
- Frontend package manifest: pass. A full Vite build was not claimed because dependency installation exceeded the execution window.
