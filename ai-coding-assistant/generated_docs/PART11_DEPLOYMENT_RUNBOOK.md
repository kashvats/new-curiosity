# Part 11 Deployment Runbook

## Base deployment

Use the default compose stack for a single scheduler instance. The default coordination backend is SQLite and background scheduling remains disabled unless explicitly enabled.

## Redis coordination profile

```bash
export IMPROVEMENT_SCHEDULER_LEASE_BACKEND=redis
export IMPROVEMENT_SCHEDULER_REDIS_URL=redis://scheduler-redis:6379/0
docker compose --profile ha-redis up -d scheduler-redis backend
```

Run `python scripts/scheduler_ha_failover_smoke.py` inside the backend environment to validate monotonically increasing fencing tokens.

## PostgreSQL coordination profile

```bash
export IMPROVEMENT_SCHEDULER_LEASE_BACKEND=postgres
export IMPROVEMENT_SCHEDULER_POSTGRES_DSN='postgresql://scheduler:...@scheduler-postgres:5432/scheduler'
docker compose --profile ha-postgres up -d scheduler-postgres backend
```

PostgreSQL is used for scheduler coordination only; the application database remains unchanged.

## OpenTelemetry profile

```bash
export IMPROVEMENT_OTEL_EXPORTER_ENDPOINT=http://otel-collector:4318
export IMPROVEMENT_INTEGRATION_ALLOW_HTTP=true
docker compose --profile observability up -d otel-collector backend
```

The backend exports scheduler logs to `/v1/logs` and scheduler traces to `/v1/traces`.

## File-backed secrets

Set `IMPROVEMENT_SECRETS_PROVIDER=file` or `env_or_file`. Mount files under `/run/secrets` using the exact setting name as the filename. Never commit real secret files.

## Probes

- `/health/live` confirms the process is alive.
- `/health/ready` verifies database access, workspace availability, the configured coordination backend, and secret-provider availability.

Use readiness, not liveness, for load-balancer traffic admission.

## Integration delivery incidents

Failed external deliveries use bounded exponential backoff. After the configured maximum attempts they move to `dead_letter`. Fix the external service or credentials, then use the retry API to return a specific delivery to `retry` state.

## Git provider status publishing

Configure `IMPROVEMENT_GITHUB_STATUS_TOKEN` and/or `IMPROVEMENT_GITLAB_STATUS_TOKEN`. Queue a publication through the scheduler integrations API. Targets are repository/project identifiers, never arbitrary URLs.

## Disaster recovery

Run a DR drill, then run restore verification against its backup. Restore verification checks SHA-256, SQLite integrity, required tables, and schedule count without overwriting the live database. Backup rotation keeps the configured number of latest DR files.
