# Build Part 8 Report — Dry-Run Guarded Scheduler & Evidence Control Plane

## Objective

Part 8 introduces the first recurring-control-plane layer, but it deliberately does **not** introduce unattended source promotion. Scheduled work is constrained to two modes:

- `observe_propose` — creates an `observe_only` improvement cycle, measures health, generates/ranks candidates, persists the recommendation, then stops.
- `canary_observe` — captures a lightweight project-health snapshot only; it never creates an improvement cycle.

No scheduler path can enter candidate repair, `WAITING_APPROVAL`, `APPLYING`, or verified-repair promotion. Automatic source apply remains disabled.

## New backend modules

- `app/improvement_scheduler_store.py`
- `app/improvement_scheduler_guards.py`
- `app/improvement_scheduler.py`
- `app/improvement_scheduler_api.py`
- `tests/test_part8_scheduler.py`

## 1. Persistent dry-run schedules

Schedules are persisted in SQLite with:

- project and schedule name,
- enabled/disabled state,
- `observe_propose` or `canary_observe` mode,
- interval,
- IANA timezone,
- optional maintenance windows,
- readiness/CI/SLO requirements,
- per-schedule daily rate limit,
- next/last run timestamps,
- bounded request options.

Potential escalation fields such as manual policy, experiment mode, candidate-selection pause, apply and confirmation fields are stripped from schedule requests. The scheduler reconstructs the request itself and hard-codes `policy="observe_only"`.

## 2. Maintenance windows

Schedules may define timezone-aware windows such as:

```json
[
  {"days": ["mon", "tue", "wed", "thu", "fri"], "start": "01:00", "end": "04:00"}
]
```

The gate supports normal and overnight windows and uses Python `zoneinfo` rather than server-local time assumptions.

## 3. Concurrency leases

Before a scheduled run proceeds it must acquire:

- `scheduler:global`
- `scheduler:project:<project_name>`

Leases have owner IDs, TTLs, heartbeats and explicit release. A second worker cannot concurrently run the same project while a live lease exists.

## 4. Rate limits

Deterministic limits cover:

- global runs per hour,
- project runs per 24 hours,
- optional schedule-specific runs per 24 hours.

Blocked/skipped executions do not count as successful scheduled work.

## 5. Emergency kill switch

A persistent global or project-scoped kill switch blocks dry-run scheduling before a cycle is created. When activated, it also requests cooperative cancellation for already-linked active scheduled dry-run cycles.

```text
POST /improvements/scheduler/kill-switch
```

Changing it requires `confirm=true`.

## 6. CI / webhook evidence

Part 8 accepts CI evidence through:

```text
POST /improvements/evidence/ci
GET  /improvements/evidence/ci
```

Supported normalized states include success/passed/succeeded and failure/failed/error/pending/cancelled.

If `IMPROVEMENT_EVIDENCE_WEBHOOK_TOKEN` is configured, ingestion requires:

```text
X-Improvement-Webhook-Token: <secret>
```

The comparison is constant-time and evidence payloads are size-bounded. Any schedule that requires CI or SLO evidence is itself blocked unless `IMPROVEMENT_EVIDENCE_WEBHOOK_TOKEN` is configured, preventing unauthenticated evidence from satisfying a scheduling gate.

## 7. SLO / error-budget evidence

SLO evidence can include:

- availability,
- error rate,
- p95 latency,
- remaining error budget.

```text
POST /improvements/evidence/slo
GET  /improvements/evidence/slo
```

Schedules that require SLO evidence are blocked unless the latest evidence is fresh and satisfies configured thresholds.

## 8. Readiness gate

Schedules default to `require_readiness=true`. Before running, the scheduler reuses the Part 7 `safe_to_automate` evidence report. This does not permit source promotion; it only allows the dry-run control plane to observe/propose.

## 9. Canary scheduling

`canary_observe` is a lower-impact scheduler mode. It:

1. passes the same kill-switch/window/rate/CI/SLO/readiness gates,
2. captures health,
3. persists a `scheduler_canary` health snapshot,
4. compares it with `IMPROVEMENT_SCHEDULER_CANARY_MIN_HEALTH`,
5. records `canary_passed` or `canary_failed`.

It creates no improvement cycle and calls no repair pipeline.

## 10. Optional background worker

The recurring worker exists but is off by default:

```text
IMPROVEMENT_DRY_RUN_SCHEDULER_ENABLED=false
```

When enabled, FastAPI starts a polling task. The worker only invokes due dry-run schedules and checks the persistent emergency kill switch on every loop.

Manual control-plane APIs remain usable while background polling is disabled.

## API surface

```text
GET    /improvements/scheduler/status
GET    /improvements/scheduler/schedules
POST   /improvements/scheduler/schedules
PUT    /improvements/scheduler/schedules/{schedule_id}
DELETE /improvements/scheduler/schedules/{schedule_id}
POST   /improvements/scheduler/schedules/{schedule_id}/run-now
POST   /improvements/scheduler/tick
GET    /improvements/scheduler/runs
GET    /improvements/scheduler/leases
POST   /improvements/scheduler/kill-switch

POST   /improvements/evidence/ci
GET    /improvements/evidence/ci
POST   /improvements/evidence/slo
GET    /improvements/evidence/slo
```

## Dashboard and VS Code

The Improvement Center now displays:

- background scheduler state,
- emergency-stop state,
- schedules and recent runs,
- schedule mode and interval,
- run-due-tick control,
- emergency-stop control.

The VS Code extension is version `1.4.0` and adds:

```text
AI Coding Assistant: Dry-Run Scheduler Status
AI Coding Assistant: Run Due Dry-Run Schedules
AI Coding Assistant: Scheduler Emergency Stop
```

## Database additions

- `improvement_schedules`
- `improvement_scheduler_runs`
- `improvement_scheduler_leases`
- `improvement_scheduler_control`
- `improvement_ci_evidence`
- `improvement_slo_evidence`

The migration remains additive and backward compatible.

## Safety invariants

Part 8 preserves all earlier manual promotion gates and additionally guarantees:

1. scheduled proposal runs use `observe_only`,
2. scheduled requests cannot request repair/experiment/apply escalation,
3. canary runs do not create improvement cycles,
4. scheduler APIs expose `scheduled_source_apply_enabled=false`,
5. `automatic_source_apply_enabled=false`,
6. the existing manual verified-repair approval/apply API remains the only source-promotion route.

## Verification baseline

```text
pytest -q
78 passed

Part 8 scheduler tests
11 passed

all `app.*` imports
MODULES 101
IMPORT_FAILURES 0

FastAPI OpenAPI
OPENAPI_PATHS 109
PART8_MISSING []

Part 8 touched-module security review
critical 0 / high 0 / medium 0 / low 0

VS Code extension
node --check extension.js
PASS

package.json
PASS
```

The frontend dependency installation was attempted but exceeded the local execution window, so a full Vite production build is not claimed as verified. The JSX integration is included and should be validated with `npm install && npm run build` in a normal development environment.

## Recommended Part 9

Part 9 should focus on production scheduler observability and evidence integrity before considering any larger autonomy step:

- signed webhook deliveries / replay protection,
- Git commit and branch binding for CI evidence,
- schedule audit logs and operator identity,
- Prometheus/OpenTelemetry scheduler metrics,
- alert routing for blocked/canary-failed runs,
- distributed lease backend option for multi-instance deployments,
- schedule preview/simulation and next-window calculation,
- shadow comparison of scheduled recommendations against human choices,
- environment-specific policies (`dev`/`staging`/`prod`).

Automatic source promotion should remain disabled until these controls have proven reliable in real operation.
