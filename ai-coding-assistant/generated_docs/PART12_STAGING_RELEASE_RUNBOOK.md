# Part 12 Staging Release Runbook

## Purpose

Use Part 12 to turn an exact verified repair into a staging-ready evidence bundle without modifying production or granting the scheduler source-write authority.

## Recommended production settings

```env
IMPROVEMENT_RELEASE_ROOT=/data/releases
IMPROVEMENT_RELEASE_BUILD_MODE=validate_only
IMPROVEMENT_RELEASE_REQUIRE_CONTAINER_BUILD=false
IMPROVEMENT_RELEASE_SIGNING_KEY=<strong-secret-or-mounted-secret>
IMPROVEMENT_RELEASE_REQUIRE_SIGNATURE=true
IMPROVEMENT_RELEASE_REQUIRE_VULNERABILITY_REPORT=true
IMPROVEMENT_RELEASE_MAX_CRITICAL_VULNS=0
IMPROVEMENT_RELEASE_MAX_HIGH_VULNS=0
IMPROVEMENT_RELEASE_MAX_MEDIUM_VULNS=20
IMPROVEMENT_RELEASE_VULN_SCANNER=report_only
IMPROVEMENT_RELEASE_WORKSPACE_TTL_HOURS=48
```

Use the Part 11 file secret provider to mount `IMPROVEMENT_RELEASE_SIGNING_KEY` instead of storing it in Compose/environment text when possible.

## Operator flow

1. Complete a manual improvement cycle until an exact repair is in `verified` state.
2. Create a release with `POST /improvements/releases` using the repair `issue_id`.
3. Run `POST /improvements/releases/{id}/run`.
4. Inspect `GET /improvements/releases/{id}/evidence`.
5. If report-only vulnerability mode is used, submit Trivy/Grype/normalized JSON to `POST /improvements/releases/{id}/vulnerabilities`.
6. If the project requires a preview, register the HTTPS preview URL with `POST /improvements/releases/{id}/preview`.
7. Confirm all gates report passed.
8. Mark the release staging-ready with `POST /improvements/releases/{id}/promote-staging` and `{ "confirm": true }`.
9. Production release remains a separate human-controlled deployment process outside Part 12.

## Docker build mode

Only enable `IMPROVEMENT_RELEASE_BUILD_MODE=docker` on an isolated build worker with the Docker CLI and daemon access. The runner invokes Docker without a shell and defaults build networking to `none`.

Do not casually mount `/var/run/docker.sock` into the general backend service; Docker daemon access is effectively host-level authority. Prefer a dedicated runner if container builds are required.

## Vulnerability evidence

Accepted shapes:

- Trivy JSON (`Results[].Vulnerabilities[]`)
- Grype JSON (`matches[]`)
- normalized `{ "findings": [{"severity":"high", ...}] }`
- normalized count-only `{ "counts": {"critical":0,"high":0,...} }`

A release with missing required evidence stops at `waiting_vulnerability_evidence`. A report over configured thresholds stops at `gates_incomplete`.

## Preview URLs

External preview URLs must use HTTPS. `http://localhost` and `http://127.0.0.1` are allowed only for local development. Preview records carry an expiry time and are marked expired during release cleanup.

## Cleanup

`POST /improvements/releases/cleanup` requires operator confirmation and removes expired isolated workspaces while retaining database evidence and signed release artifacts.

## Incident handling

If a release is suspicious or failed, call `/reject`. Do not promote it staging-ready. Revoke or discard the original verified candidate separately when appropriate.

No Part 12 route deploys to production, applies the repair to the live project, or bypasses the Part 6/7 governance and approval path.
