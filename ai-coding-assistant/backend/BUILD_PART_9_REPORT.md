# Build Part 9 Report — Production-Hardened Dry-Run Scheduler

## Goal

Harden the Part 8 observe/propose-only scheduler for production-style operation while preserving the manual live-source apply boundary.

## Implemented

1. HMAC-SHA256 signed CI/SLO evidence with timestamp freshness checking.
2. Persistent delivery-ID replay protection.
3. Backwards-compatible Part 8 token authentication when HMAC is not configured.
4. CI branch/commit binding and optional binding to the current project Git HEAD.
5. `dev`, `staging`, and `prod` deterministic scheduler environment policies.
6. Authenticated operator registry and immutable-style scheduler audit entries.
7. Monotonic database-backed fencing tokens for scheduler leases.
8. Side-effect-free schedule simulation/preview.
9. Persisted alerts for blocked, error, and canary-failed runs.
10. Alert acknowledgement with operator identity.
11. Persisted run telemetry and JSON/Prometheus metrics.
12. Dashboard integration for environment selection, simulation, operator identity, hardening status, metrics and alerts.
13. VS Code extension 1.5.0 simulation, metrics/alerts, hardening status and operator prompts.

## New backend modules

- `app/improvement_scheduler_security.py`
- `app/improvement_scheduler_environment.py`
- `app/improvement_scheduler_observability.py`

## Persistence additions

- `improvement_webhook_deliveries`
- `improvement_operator_audit`
- `improvement_scheduler_alerts`
- `improvement_scheduler_telemetry`
- `improvement_scheduler_lease_fences`

Additive columns:

- schedules: `environment`, `ci_branch`, `ci_commit_sha`, `bind_ci_to_project_head`
- leases: `fence_token`

## New API surface

```text
POST /improvements/scheduler/simulate
GET  /improvements/scheduler/schedules/{schedule_id}/simulate
GET  /improvements/scheduler/metrics
GET  /improvements/scheduler/metrics/prometheus
GET  /improvements/scheduler/telemetry
GET  /improvements/scheduler/alerts
POST /improvements/scheduler/alerts/{alert_id}/ack
GET  /improvements/scheduler/audit
```

## Security properties

- evidence signatures use constant-time HMAC comparison,
- signed timestamps have a configurable skew window,
- delivery IDs are unique and replay-protected,
- operator tokens are read from configuration and never persisted,
- audit records contain identity/role/action metadata but not credentials,
- fencing tokens increase across lease release/reacquisition,
- scheduled requests remain force-sanitized to observe-only behavior,
- no Part 9 path enables automatic source apply.

## Verification

- Part 8 baseline before modification: `78 passed`
- Part 9 tests: `10 passed`
- Full backend suite: `88 passed`

See the final package validation output for import/OpenAPI/extension/security checks.

## Final validation

- Full backend suite: **88 passed**
- Backend app modules discovered: **104**
- Import failures: **0**
- OpenAPI paths: **117**
- Missing required Part 9 paths: **0**
- Deterministic security review of Part 9 scheduler/control modules: **0 critical / 0 high / 0 medium / 0 low**
- VS Code extension JavaScript syntax: **PASS**
- VS Code extension manifest JSON: **PASS**
- Frontend manifest JSON: **PASS**
- Docker Compose YAML: **PASS**

### Frontend production-build caveat

The archive does not include `frontend/node_modules`. A direct `npm run build` therefore reported `vite: not found`. A subsequent dependency-install/build attempt exceeded the execution window. The Part 9 JSX integration is included, but a complete Vite production build is not claimed as verified in this environment.
