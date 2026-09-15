# Scheduler Operations Runbook — Part 10

This runbook covers the **dry-run scheduler control plane only**. Scheduled and automatic source apply remain disabled.

## 1. Deployment modes

### Single instance / local
Use the default:

```env
IMPROVEMENT_SCHEDULER_LEASE_BACKEND=sqlite
```

SQLite leases are appropriate when all scheduler workers share the same application database and filesystem.

### Multi-instance / shared coordination
Choose one shared backend:

```env
IMPROVEMENT_SCHEDULER_LEASE_BACKEND=redis
IMPROVEMENT_SCHEDULER_REDIS_URL=redis://redis:6379/0
```

or:

```env
IMPROVEMENT_SCHEDULER_LEASE_BACKEND=postgres
IMPROVEMENT_SCHEDULER_POSTGRES_DSN=postgresql://user:pass@postgres/db
```

Install `backend/requirements-operations.txt` for optional HA dependencies. Fencing tokens remain monotonic and leader election uses the same backend.

## 2. Leader election

Background workers use the `scheduler:leader` lease before polling due schedules. Keep enabled in multi-instance deployments:

```env
IMPROVEMENT_SCHEDULER_LEADER_ELECTION_ENABLED=true
IMPROVEMENT_SCHEDULER_LEADER_LEASE_TTL_SECONDS=120
```

Per-project and global run leases still protect execution after leader election.

## 3. External alert webhook

Configure an HTTPS sink:

```env
IMPROVEMENT_ALERT_WEBHOOK_URL=https://ops.example.com/ai-scheduler-alerts
IMPROVEMENT_ALERT_WEBHOOK_SIGNING_SECRET=<secret>
```

Alerts are first persisted locally, then placed in a durable delivery outbox. Delivery failures do not erase the alert. Retry with:

```text
POST /improvements/scheduler/integrations/flush
```

Outgoing signatures use `X-AI-Scheduler-Timestamp` and `X-AI-Scheduler-Signature: sha256=<hex>` over `timestamp.body`.

## 4. OpenTelemetry export

Configure an OTLP/HTTP collector base URL:

```env
IMPROVEMENT_OTEL_EXPORTER_ENDPOINT=https://otel-collector.example.com
IMPROVEMENT_OTEL_EXPORTER_HEADERS_JSON={"Authorization":"Bearer ..."}
```

The backend exports scheduler telemetry to `/v1/logs`. Failed exports remain unmarked and are retried on a later integration flush.

## 5. Native Git provider evidence

### GitHub
Set:

```env
IMPROVEMENT_GITHUB_WEBHOOK_SECRET=<github-webhook-secret>
```

Send GitHub events to:

```text
POST /improvements/evidence/github?project_name=<project>
```

The adapter verifies `X-Hub-Signature-256`, requires `X-GitHub-Delivery`, rejects replayed delivery IDs, and normalizes workflow/check/push/PR provenance into CI evidence.

### GitLab
Set:

```env
IMPROVEMENT_GITLAB_WEBHOOK_TOKEN=<gitlab-secret-token>
```

Send events to:

```text
POST /improvements/evidence/gitlab?project_name=<project>
```

The adapter verifies `X-Gitlab-Token`, requires `X-Gitlab-Event-UUID`, rejects replayed delivery IDs, and normalizes pipeline/job provenance.

## 6. Retention and compaction

Preview first:

```text
GET /improvements/scheduler/admin/retention/preview
```

Then execute only with authenticated operator credentials and explicit confirmation:

```text
POST /improvements/scheduler/admin/retention/compact
{"confirm":true,"vacuum":false}
```

Retention targets old replay records, operator audit rows, completed scheduler runs, delivered integration outbox rows, old telemetry, and acknowledged alerts. Active schedules and current control state are not deleted.

## 7. Emergency response

1. Activate the global kill switch.
2. Verify active scheduler-linked observe-only cycles received cancellation requests.
3. Inspect `/improvements/scheduler/alerts`, `/metrics`, and `/audit`.
4. Confirm the current leader/lease backend in `/improvements/scheduler/status`.
5. Correct CI/SLO/integration evidence or infrastructure.
6. Simulate schedules before clearing the kill switch.
7. Clear the kill switch only with an authenticated operator.

## 8. Invariant

No HA backend, leader election result, webhook, Git provider event, telemetry export, operator role, or DR result can grant scheduled source-write authority.

```text
scheduled_source_apply_enabled = false
automatic_source_apply_enabled = false
```
