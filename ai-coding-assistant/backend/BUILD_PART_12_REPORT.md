# Build Part 12 Report — Candidate-to-Staging Release Orchestration

## Goal

Part 12 adds a staging/release orchestration layer on top of the governed improvement system without introducing production auto-promotion. An exact `verified_repairs` candidate can be copied into an isolated release workspace, validated, optionally container-built, supplied with SBOM/vulnerability/signature evidence, and explicitly marked `staging_ready` by an authenticated operator.

## Safety invariant

Part 12 has no production deployment or production promotion API. Release records persist `production_promotion_allowed = 0`, evidence bundles repeat that invariant, and scheduled source apply remains disabled.

The live project is never changed by release preparation. The exact verified patch is applied only inside a release workspace under `IMPROVEMENT_RELEASE_ROOT`.

## New modules

- `app/improvement_release_store.py` — release/check/artifact/preview persistence.
- `app/improvement_release_security.py` — CycloneDX SBOM generation, HMAC-SHA256 evidence signing, vulnerability report normalization and optional Trivy adapter.
- `app/improvement_release_orchestrator.py` — isolated workspace preparation, validation, optional Docker build, staging manifest, evidence bundle, preview registration, staging-ready gate and cleanup.
- `app/improvement_release_api.py` — operator-audited FastAPI surface.

## Persistence

Part 12 adds four additive SQLite tables:

- `improvement_release_candidates`
- `improvement_release_checks`
- `improvement_release_artifacts`
- `improvement_preview_environments`

Release candidates carry the source verified-repair issue id, optional SCM commit/target, release state, isolated workspace path, evidence summary, failure reason, and an immutable default `production_promotion_allowed=0` flag.

## Release state flow

```text
verified repair
     ↓
created
     ↓
preparing
     ↓
prepared
     ↓
validation
     ↓
SBOM + signatures + staging manifest
     ↓
vulnerability evidence
     ↓
optional preview evidence
     ↓
waiting_staging_approval
     ↓ explicit operator confirm
staging_ready
```

Common blocked states include `validation_failed`, `build_failed`, `waiting_vulnerability_evidence`, `gates_incomplete`, `pipeline_failed`, and `rejected`.

## Candidate workspaces

A release creates `<IMPROVEMENT_RELEASE_ROOT>/<release-id>/workspace`, copies the current project while excluding VCS/build/cache directories, and applies the exact verified repair there using the existing patch engine. This preserves expected-hash stale-write checks while avoiding live-source mutation.

Workspaces are TTL-cleanable. Release database records and release evidence artifacts remain after workspace cleanup.

## Validation and integration tests

The release runner reuses persisted machine-verification commands from the verified repair and supplements them with deterministic project check discovery. Results are persisted as both `candidate_validation` and first-class `integration_tests` release checks.

## Container builds

`IMPROVEMENT_RELEASE_BUILD_MODE=validate_only` is the default. `docker` mode enables a fixed-argument, `shell=False` Docker build against the isolated candidate workspace.

Docker build networking defaults to `none`. Actual Docker mode should only be enabled on a dedicated build host/runner with an appropriately isolated Docker daemon. The default backend container does not mount the Docker socket.

`IMPROVEMENT_RELEASE_REQUIRE_CONTAINER_BUILD=true` makes a passing container build a staging gate.

## SBOM and staging manifest

The release pipeline generates:

- `sbom.cdx.json` — deterministic CycloneDX 1.5 dependency inventory from Python and Node manifests.
- `staging-manifest.json` — release id, project, issue id, commit, build mode/image, workspace TTL and explicit `productionPromotionAllowed=false`.
- `release-evidence.json` — aggregate checks, artifact metadata, previews and gate results.

Artifacts use SHA-256 digests. When `IMPROVEMENT_RELEASE_SIGNING_KEY` is configured, evidence digests are HMAC-SHA256 signed without storing the signing key.

## Vulnerability gates

The default scanner mode is `report_only`. The API accepts Trivy JSON, Grype JSON, or a normalized `{findings:[...]}` payload. Critical/high/medium maximums are configurable and staging readiness is blocked when thresholds are exceeded.

`IMPROVEMENT_RELEASE_VULN_SCANNER=trivy` enables a fixed-argument local Trivy filesystem adapter. Vulnerability DB lifecycle is left to deployment infrastructure.

## Preview environments

Part 12 records preview environments with TTLs. `external` preview URLs must use HTTPS, except localhost development URLs. `none` records a workspace-only preview and does not satisfy a release that explicitly requires a preview URL.

## SCM checks

When a release is created with `scm_provider`, `scm_target`, and `commit_sha`, the existing Part 11 GitHub/GitLab status-publication outbox is reused with context `ai-coding-assistant/staging-readiness`.

## APIs

- `GET /improvements/releases/capabilities`
- `GET /improvements/releases`
- `POST /improvements/releases`
- `POST /improvements/releases/cleanup`
- `GET /improvements/releases/{release_id}`
- `GET /improvements/releases/{release_id}/evidence`
- `POST /improvements/releases/{release_id}/run`
- `POST /improvements/releases/{release_id}/vulnerabilities`
- `POST /improvements/releases/{release_id}/preview`
- `POST /improvements/releases/{release_id}/promote-staging`
- `POST /improvements/releases/{release_id}/reject`

There is deliberately no production-promotion endpoint.

## UI surfaces

The project Improvement Center now includes a Part 12 staging-release panel. A verified improvement waiting for source approval can be sent to staging orchestration without first changing the live source tree.

VS Code extension 1.8.0 adds `AI Coding Assistant: Staging Release Center`.

## Validation

Part 12 adds `tests/test_part12_release_orchestration.py` covering schema/capabilities, isolated patch application, vulnerability evidence, vulnerability threshold blocking, CycloneDX/signatures, HTTPS preview rules, explicit staging promotion, fixed Docker invocation, workspace cleanup, route registration and absence of production-promotion routes.

Verified during construction: **121 backend tests pass**.

## Final validation

- Full backend suite: **121 passed**.
- Backend modules discovered/imported: **115 / 115**, **0 failures**.
- FastAPI route count: **146**.
- Part 12 release routes: **10**, all present.
- Production release-promotion routes: **0**.
- Deterministic security gate for Part 12 modules: **0 critical / 0 high / 0 medium / 0 low**.
- VS Code extension JavaScript syntax: pass.
- VS Code and frontend package manifests: valid JSON.
- Docker Compose YAML: parses successfully with 7 services.
- Frontend production build: not claimed; dependency installation exceeded the execution window.
