#!/usr/bin/env python3
"""Non-destructive Part 16 smoke checks for production deployer hardening.

Run inside the production-deployer container or with PYTHONPATH=production-deployer.
No production deployment commands are executed.
"""
from __future__ import annotations
import json
from app.hardening import capabilities, concurrency_snapshot, migration_safety_check, chaos_simulation

result={
    "capabilities":capabilities(),
    "migration_safety":migration_safety_check(),
    "concurrency":concurrency_snapshot(),
    "chaos":{name:chaos_simulation(scenario=name) for name in ("database_locked","callback_unavailable","stale_authorization","operator_auth_failure")},
}
print(json.dumps(result,indent=2,sort_keys=True))
if not result["migration_safety"]["passed"] or not result["concurrency"]["within_limit"]:
    raise SystemExit(2)
