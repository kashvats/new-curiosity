# Scheduler Disaster-Recovery Runbook — Part 10

## Goal

Verify that scheduler/control-plane persistence can be copied and read back without overwriting the live database.

## Routine drill

Run with authenticated operator credentials:

```text
POST /improvements/scheduler/admin/dr-drill
{"confirm":true}
```

The drill:

1. uses SQLite's backup API to create a point-in-time copy,
2. opens the copy independently,
3. executes `PRAGMA integrity_check`,
4. verifies required scheduler/audit/control tables,
5. counts persisted schedules,
6. records file size and SHA-256,
7. persists the drill result in the live database,
8. never restores over the live database.

Review history:

```text
GET /improvements/scheduler/admin/dr-drills
```

## Real recovery procedure

1. Activate the global scheduler kill switch before any restore.
2. Stop all scheduler-enabled backend replicas.
3. Preserve the damaged database and WAL/SHM files for investigation.
4. Choose a verified backup whose SHA-256 and integrity result are known.
5. Restore into a **new path**, not over the current database first.
6. Run SQLite integrity checks and inspect scheduler tables, operator audit, policies, readiness evidence, and schedules.
7. Point a single non-production backend instance at the restored database and verify `/health` plus scheduler status/simulation APIs.
8. Only after validation, promote the restored database according to your normal change-management procedure.
9. Start one scheduler replica, confirm leader election, then start remaining replicas.
10. Keep the kill switch active until schedule simulations and CI/SLO evidence are healthy.

## Important limitation

The built-in drill validates the SQLite control-plane database. If Redis/PostgreSQL is used only for ephemeral lease coordination, lease state does not need restoration; stale leases should expire naturally. Persistent application data outside this SQLite database must follow its own backup procedure.
