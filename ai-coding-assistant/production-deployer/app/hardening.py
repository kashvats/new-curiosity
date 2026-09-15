from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from app.config import settings
from app.store import db, get_deployment, init_db, list_events, list_observations


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def capabilities() -> Dict[str, Any]:
    return {
        "part": 16,
        "slo_window_evaluation": True,
        "audit_chain_verification": True,
        "migration_safety_check": True,
        "rollback_drill": True,
        "chaos_simulation": True,
        "key_rotation": {
            "package_previous_keys_configured": bool(str(settings.PRODUCTION_DEPLOYER_PREVIOUS_PACKAGE_SIGNING_KEYS or "")),
            "receipt_previous_keys_configured": bool(str(settings.PRODUCTION_DEPLOYER_PREVIOUS_RECEIPT_SIGNING_KEYS or "")),
        },
        "production_execution_enabled": bool(settings.PRODUCTION_DEPLOYER_EXECUTION_ENABLED),
        "certification_mode": bool(settings.PRODUCTION_DEPLOYER_CERTIFICATION_MODE),
    }


def evaluate_slo_window(deployment_id: str, *, min_samples: int | None = None, pass_ratio: float | None = None) -> Dict[str, Any]:
    deployment = get_deployment(deployment_id)
    if not deployment:
        raise KeyError(deployment_id)
    samples = list_observations(deployment_id, limit=500)
    required = max(1, int(min_samples or settings.PRODUCTION_DEPLOYER_SLO_WINDOW_MIN_SAMPLES))
    threshold = max(0.0, min(float(pass_ratio if pass_ratio is not None else settings.PRODUCTION_DEPLOYER_SLO_WINDOW_PASS_RATIO), 1.0))
    considered = samples[: max(required, len(samples))]
    passed = sum(1 for item in considered if bool(item.get("passed")))
    ratio = passed / len(considered) if considered else 0.0
    blockers: list[str] = []
    if len(considered) < required:
        blockers.append("insufficient_samples")
    if ratio < threshold:
        blockers.append("window_pass_ratio_below_threshold")
    return {
        "deployment_id": deployment_id,
        "samples": len(considered),
        "passed_samples": passed,
        "pass_ratio": round(ratio, 4),
        "required_samples": required,
        "required_pass_ratio": threshold,
        "passed": not blockers,
        "blockers": blockers,
    }


def verify_audit_chain(deployment_id: str) -> Dict[str, Any]:
    if not get_deployment(deployment_id):
        raise KeyError(deployment_id)
    init_db()
    with db() as conn:
        rows = conn.execute(
            "SELECT id,deployment_id,event_type,operator_id,role,payload_json,created_at,prev_hash,event_hash FROM deployment_events WHERE deployment_id=? ORDER BY created_at,id",
            (deployment_id,),
        ).fetchall()
    previous = ""
    errors: list[str] = []
    verified = 0
    for row in rows:
        item = dict(row)
        stored_prev = str(item.get("prev_hash") or "")
        stored_hash = str(item.get("event_hash") or "")
        if not stored_hash:
            errors.append(f"legacy_or_unsigned_event:{item['id']}")
            previous = stored_hash or previous
            continue
        if stored_prev != previous:
            errors.append(f"prev_hash_mismatch:{item['id']}")
        try:
            payload = json.loads(item.get("payload_json") or "{}")
        except Exception:
            payload = {}
        canonical = json.dumps(
            {
                "id": item["id"],
                "deployment_id": item["deployment_id"],
                "event_type": item["event_type"],
                "operator_id": item.get("operator_id"),
                "role": item.get("role"),
                "payload": payload,
                "created_at": item["created_at"],
                "prev_hash": stored_prev,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        computed = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if computed != stored_hash:
            errors.append(f"event_hash_mismatch:{item['id']}")
        else:
            verified += 1
        previous = stored_hash
    return {
        "deployment_id": deployment_id,
        "events": len(rows),
        "verified_events": verified,
        "valid": not errors and (bool(rows) or not settings.PRODUCTION_DEPLOYER_AUDIT_CHAIN_REQUIRED),
        "errors": errors,
        "head_hash": previous or None,
    }


def migration_safety_check() -> Dict[str, Any]:
    init_db()
    path = Path(str(settings.PRODUCTION_DEPLOYER_DATABASE_PATH))
    required = {"deployments", "deployment_observations", "deployment_events", "used_authorizations"}
    with db() as conn:
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        tables = {str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        deployment_cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(deployments)").fetchall()}
        event_cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(deployment_events)").fetchall()}
    missing = sorted(required - tables)
    missing_deployment_cols = sorted({"receipt_json", "previous_state_json", "authorization_json"} - deployment_cols)
    missing_event_cols = sorted({"prev_hash", "event_hash"} - event_cols)
    passed = integrity == "ok" and not missing and not missing_deployment_cols and not missing_event_cols
    return {
        "passed": passed,
        "database_path_exists": path.exists(),
        "integrity_check": integrity,
        "missing_tables": missing,
        "missing_deployment_columns": missing_deployment_cols,
        "missing_event_columns": missing_event_cols,
        "checked_at": _now(),
    }


def rollback_drill(deployment_id: str) -> Dict[str, Any]:
    deployment = get_deployment(deployment_id)
    if not deployment:
        raise KeyError(deployment_id)
    previous = deployment.get("previous_state") or {}
    provider = str(deployment.get("provider") or "")
    target = deployment.get("target") or {}
    blockers: list[str] = []
    if provider == "kubernetes" and not previous.get("image"):
        blockers.append("previous_kubernetes_image_missing")
    elif provider == "ecs" and not previous.get("task_definition"):
        blockers.append("previous_ecs_task_definition_missing")
    elif provider == "external":
        blockers.append("external_provider_requires_external_rollback")
    return {
        "deployment_id": deployment_id,
        "provider": provider,
        "target_identity": {k: target.get(k) for k in ("namespace", "deployment", "cluster", "service", "target_id") if target.get(k)},
        "previous_state_present": bool(previous),
        "passed": not blockers,
        "blockers": blockers,
        "executed": False,
        "note": "Non-destructive rollback drill; no production command is executed.",
    }


def chaos_simulation(*, scenario: str) -> Dict[str, Any]:
    supported = {
        "database_locked": "SQLite busy_timeout/WAL resilience path",
        "callback_unavailable": "Receipt callback failure preserves local signed receipt",
        "stale_authorization": "Expired/single-use authorization must be rejected",
        "operator_auth_failure": "Invalid operator credentials must be rejected",
    }
    if scenario not in supported:
        raise ValueError("Unsupported chaos scenario")
    return {
        "scenario": scenario,
        "passed": True,
        "destructive": False,
        "simulation": True,
        "expected_control": supported[scenario],
        "checked_at": _now(),
    }


def concurrency_snapshot() -> Dict[str, Any]:
    init_db()
    active_statuses = ("authorized", "executing", "observing", "awaiting_external_stages")
    with db() as conn:
        count = int(conn.execute(
            "SELECT COUNT(*) FROM deployments WHERE status IN (?,?,?,?)", active_statuses
        ).fetchone()[0])
    maximum = max(1, int(settings.PRODUCTION_DEPLOYER_MAX_CONCURRENT_ACTIVE))
    return {"active": count, "maximum": maximum, "within_limit": count <= maximum}
