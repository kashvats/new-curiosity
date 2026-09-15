# Build Part 10 Report — Deployment & Operations Hardening

Part 10 extends the Part 9 dry-run scheduler into a deployable operations/control-plane layer while preserving the manual source-promotion boundary.

## Implemented

### External delivery integrations
- durable alert-webhook outbox,
- optional HMAC-SHA256 signatures for outgoing alerts,
- HTTPS-only endpoints by default,
- retryable manual/background integration flush,
- optional OTLP/HTTP scheduler telemetry export,
- persisted OTEL export success/error state.

### HA coordination and leader election
- lease backend abstraction with `sqlite`, optional `redis`, and optional `postgres`,
- monotonic fencing retained across backends,
- leader election for background polling,
- leader lease heartbeat during scheduler ticks,
- per-run global/project fencing remains in place,
- optional HA dependencies isolated in `requirements-operations.txt`.

### Native Git provenance
- GitHub HMAC webhook verification,
- GitLab secret-token verification,
- provider-native workflow/pipeline/commit/branch normalization,
- delivery-ID replay protection using the existing persisted delivery ledger.

### Data lifecycle and disaster recovery
- retention preview,
- authenticated/confirmed retention + optional SQLite VACUUM,
- point-in-time SQLite backup drill,
- independent integrity/table verification,
- SHA-256/size evidence,
- persisted DR drill history,
- operations and DR runbooks.

### Surfaces
- new FastAPI integration/provenance/admin APIs,
- dashboard HA/integration status + flush/DR controls,
- VS Code extension 1.6.0 integration/HA and DR commands.

## New modules

```text
app/improvement_scheduler_ha.py
app/improvement_scheduler_integrations.py
app/improvement_scheduler_provenance.py
app/improvement_scheduler_admin.py
```

## New APIs

```text
GET  /improvements/scheduler/integrations
POST /improvements/scheduler/integrations/flush
POST /improvements/evidence/github
POST /improvements/evidence/gitlab
GET  /improvements/scheduler/admin/retention/preview
POST /improvements/scheduler/admin/retention/compact
POST /improvements/scheduler/admin/dr-drill
GET  /improvements/scheduler/admin/dr-drills
```

## Persistence additions

```text
improvement_scheduler_deliveries
improvement_scheduler_dr_drills
improvement_scheduler_telemetry.otel_exported_at
improvement_scheduler_telemetry.otel_export_error
```

## Safety invariant

Part 10 coordinates and observes the recurring dry-run control plane. It does not add any route from a schedule to live source promotion.

```text
scheduled_source_apply_enabled = false
automatic_source_apply_enabled = false
```

## Verification

Part 10 adds `tests/test_part10_deployment_operations.py` covering schema migration, alert outbox/signing, OTLP export, HA fencing, GitHub/GitLab provenance, native replay protection, retention, DR drills, HTTP endpoint hardening, and API/status registration.

## Final validation

```text
pytest -q
99 passed

backend modules: 108
import failures: 0
OpenAPI paths: 129
missing required Part 10 paths: 0
```

The deterministic security gate reports:

```text
critical: 0
high:     0
medium:   0
low:      0
```

VS Code `extension.js` syntax and both extension/frontend JSON manifests validate. Docker Compose parses as YAML.

Frontend production-build validation remains environment-limited: `npm install --no-audit --no-fund` exceeded the local execution window and therefore `vite` was not installed. The dashboard code is included, but this report does not claim a successful Vite production build.
