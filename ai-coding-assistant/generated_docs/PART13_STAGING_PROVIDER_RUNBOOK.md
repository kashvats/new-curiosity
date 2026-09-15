# Part 13 Staging Provider & Release Handoff Runbook

## Purpose

Part 13 deploys **staging only**. It accepts a Part 12 `staging_ready` candidate, coordinates staging delivery/validation, generates provenance, supports staging rollback, and creates a human-authorized release request for a separate production release system.

It does not deploy production.

## Recommended default settings

```env
IMPROVEMENT_STAGING_EXECUTION_ENABLED=false
IMPROVEMENT_STAGING_CI_TRIGGER_ENABLED=false
IMPROVEMENT_STAGING_OCI_EXECUTION_ENABLED=false
IMPROVEMENT_STAGING_PRODUCTION_DENY_TOKENS=prod,production
IMPROVEMENT_STAGING_GITHUB_WORKFLOW=staging.yml
IMPROVEMENT_RELEASE_COSIGN_ENABLED=false
IMPROVEMENT_STAGING_AUTO_TEARDOWN_EXPIRED=false
IMPROVEMENT_PRODUCTION_REQUEST_REQUIRE_VERIFIED_OPERATOR=true
IMPROVEMENT_PRODUCTION_REQUEST_ALLOWED_ROLES=release-manager,maintainer
```

Keep execution disabled in the general backend. If direct Kubernetes/ECS/OCI operations are required, use a dedicated staging runner with the minimum cloud/RBAC permissions for a staging namespace/account/cluster.

## GitHub Actions / GitLab pipeline trigger

`POST /improvements/staging/releases/{release_id}/ci/trigger`

GitHub requires `scm_target=owner/repository`. GitLab uses the configured project path/ID. With `IMPROVEMENT_STAGING_CI_TRIGGER_ENABLED=false`, the API returns `planned` and causes no provider-side action.

Provider tokens can be mounted with the Part 11 file secret provider:

- `IMPROVEMENT_GITHUB_ACTIONS_TOKEN`
- `IMPROVEMENT_GITLAB_PIPELINE_TOKEN`

## OCI staging promotion

`POST /improvements/staging/releases/{release_id}/oci/promote`

The destination image reference must be staging-scoped. Production-like target tokens are rejected. Direct `docker pull/tag/push` requires `IMPROVEMENT_STAGING_OCI_EXECUTION_ENABLED=true` and an appropriately isolated runner.

## Staging deployment

`POST /improvements/staging/releases/{release_id}/deployments`

Providers:

- `external` — register an already-provisioned HTTPS staging URL.
- `kubernetes` — generate a namespaced staging Deployment manifest; optionally execute `kubectl apply`.
- `ecs` — generate staging ECS update parameters; optionally execute a fixed `aws ecs update-service` call.

If deployment happens externally (for example through CI), report the provider outcome with:

`POST /improvements/staging/deployments/{deployment_id}/evidence`

Only a `ready` deployment can enter staging tests.

## Staging tests

`POST /improvements/staging/deployments/{deployment_id}/tests`

Submit one or more `smoke`, `api`, or `e2e` checks as argv arrays. They pass through the backend's existing safe-command policy. No shell command strings are accepted.

When all checks pass:

- the deployment becomes `validated`,
- SLSA provenance is generated if missing,
- the release becomes `staging_validated`,
- GitHub/GitLab commit status can be queued as `ai-coding-assistant/staging-validation`.

## Provenance / Cosign

Generate provenance explicitly with:

`POST /improvements/staging/releases/{release_id}/attestations/slsa`

Optional OCI attestation:

`POST /improvements/staging/releases/{release_id}/attestations/cosign`

Cosign remains disabled until `IMPROVEMENT_RELEASE_COSIGN_ENABLED=true`. Configure Cosign credentials/identity in the dedicated release runner; the backend does not manufacture signing credentials.

## Rollback and teardown

Set `IMPROVEMENT_STAGING_AUTO_TEARDOWN_EXPIRED=true` to let the existing leader-elected scheduler tick tear down expired preview records and linked staging deployments. The default is false.


Rollback a staging deployment:

`POST /improvements/staging/deployments/{deployment_id}/rollback`

Tear down a preview record:

`POST /improvements/staging/previews/{preview_id}/teardown`

Kubernetes rollback can directly delete the generated manifest when execution is enabled. ECS previous-task restoration is environment-specific, so the adapter records `rollback_requested` and leaves the actual previous task-definition selection to your deployment policy.

## Production release handoff

`POST /improvements/staging/releases/{release_id}/production-release-request`

Body:

```json
{"confirm": true, "notes": "staging validation approved"}
```

By default this requires a verified operator with `release-manager` or `maintainer` role. The request stores an evidence digest, release-signature envelope, and operator identity. It **does not** call Kubernetes, ECS, Docker, GitHub Actions, GitLab, or any production CD endpoint.

Your production release system should consume the request/evidence separately and perform its own production authorization.

## Incident response

If staging fails:

1. do not create a production release request,
2. run the staging rollback endpoint,
3. tear down the preview,
4. inspect Part 12 + Part 13 evidence,
5. create a new verified candidate rather than modifying the staged workspace in place.
