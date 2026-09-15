"""Part 15 production deployment outcome ingestion and conservative learning feedback.

The independent production deployer signs terminal receipts with a secret that is
configured separately from production credentials. This backend verifies and stores the
receipt, then uses the outcome as evidence when ranking future improvement strategies.
No deployment authority is introduced here.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.config import settings
from app.database import get_db, init_database
from app.improvement_production_governance_store import get_deployment_package
from app.improvement_release_store import get_release_candidate
from app.improvement_secrets import get_secret
from app.improvement_staging_security import canonical_digest

_TERMINAL_STATUSES = {"succeeded", "failed", "rolled_back", "halted", "aborted"}
_FAILURE_STATUSES = {"failed", "rolled_back", "halted", "aborted"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _receipt_key() -> str:
    return get_secret("IMPROVEMENT_PRODUCTION_OUTCOME_SIGNING_KEY") or str(
        getattr(settings, "IMPROVEMENT_PRODUCTION_OUTCOME_SIGNING_KEY", "") or ""
    )


def production_feedback_capabilities() -> Dict[str, Any]:
    return {
        "part": 15,
        "signed_production_outcomes": True,
        "outcome_signing_configured": bool(_receipt_key()),
        "production_strategy_learning": True,
        "production_failure_risk_escalation": True,
        "backend_can_execute_production": False,
        "production_credentials_stored": False,
    }


def _verify_receipt_signature(digest_sha256: str, signature: str) -> bool:
    if not signature:
        return False
    keys=[]
    current=_receipt_key()
    if current:
        keys.append(current)
    for item in str(getattr(settings,"IMPROVEMENT_PRODUCTION_OUTCOME_PREVIOUS_SIGNING_KEYS","") or "").split(","):
        item=item.strip()
        if item and item not in keys:
            keys.append(item)
    message=f"production-deployment-receipt:{digest_sha256}".encode("utf-8")
    for key in keys:
        expected=hmac.new(key.encode("utf-8"),message,hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected,str(signature)):
            return True
    return False


def _candidate_strategy_for_release(release_id: str, project_name: str) -> str | None:
    release = get_release_candidate(release_id)
    if not release:
        return None
    issue_id = str(release.get("issue_id") or "")
    if not issue_id:
        return None
    init_database()
    with get_db() as conn:
        row = conn.execute(
            """SELECT c.strategy_key
               FROM improvement_candidates c
               JOIN improvement_cycles y ON y.id=c.cycle_id
               WHERE c.issue_id=? AND y.project_name=? AND c.strategy_key IS NOT NULL
               ORDER BY COALESCE(c.updated_at,c.created_at) DESC LIMIT 1""",
            (issue_id, project_name),
        ).fetchone()
    return str(row[0]) if row and row[0] else None


def ingest_production_outcome(*, payload: Dict[str, Any], digest_sha256: str, signature: str) -> Dict[str, Any]:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    if len(encoded) > max(1024, int(getattr(settings, "IMPROVEMENT_PRODUCTION_OUTCOME_MAX_BYTES", 1_000_000))):
        raise ValueError("Production outcome exceeds configured size limit")
    computed = canonical_digest(payload)
    if computed != str(digest_sha256 or ""):
        raise ValueError("Production outcome digest mismatch")
    if not _verify_receipt_signature(computed, signature):
        raise ValueError("Production outcome signature is invalid")
    if str(payload.get("schema") or "") != "ai-coding-assistant.production-deployment-receipt.v1":
        raise ValueError("Unsupported production outcome schema")
    status = str(payload.get("status") or "").lower()
    if status not in _TERMINAL_STATUSES:
        raise ValueError("Production outcome must be terminal")
    deployment_id = str(payload.get("deployment_id") or "").strip()
    package_id = str(payload.get("package_id") or "").strip()
    project_name = str(payload.get("project_name") or "").strip()
    release_id = str(payload.get("release_id") or "").strip()
    if not deployment_id or not package_id or not project_name or not release_id:
        raise ValueError("deployment_id, package_id, project_name and release_id are required")
    package = get_deployment_package(package_id)
    if not package:
        raise ValueError("Production outcome references an unknown deployment package")
    package_payload = package.get("payload") or {}
    if str(package_payload.get("project_name") or "") != project_name:
        raise ValueError("Production outcome project does not match deployment package")
    if str(package_payload.get("release_id") or "") != release_id:
        raise ValueError("Production outcome release does not match deployment package")
    if payload.get("commit_sha") and str(package_payload.get("commit_sha") or "") != str(payload.get("commit_sha") or ""):
        raise ValueError("Production outcome commit does not match deployment package")

    strategy_key = _candidate_strategy_for_release(release_id, project_name)
    failure_class = str(payload.get("failure_class") or "").strip() or None
    if not failure_class and status in _FAILURE_STATUSES:
        failure_class = {
            "rolled_back": "production_rollback",
            "halted": "production_slo_halt",
            "failed": "production_deploy_failure",
            "aborted": "production_operator_abort",
        }.get(status)
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    outcome_id = str(uuid.uuid4())
    created_at = _now()
    init_database()
    try:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO improvement_production_outcomes
                   (id,deployment_id,package_id,authorization_id,case_id,release_id,project_name,commit_sha,provider,
                    rollout_strategy,status,failure_class,candidate_strategy_key,metrics_json,payload_json,
                    receipt_digest,signature,signature_algorithm,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    outcome_id, deployment_id, package_id, payload.get("authorization_id"), package.get("case_id"),
                    release_id, project_name, payload.get("commit_sha"), payload.get("provider"),
                    payload.get("rollout_strategy"), status, failure_class, strategy_key,
                    json.dumps(metrics, ensure_ascii=False, sort_keys=True, default=str),
                    json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str), computed, signature,
                    "hmac-sha256", created_at,
                ),
            )
            conn.commit()
    except Exception as exc:
        text = str(exc).lower()
        if "unique" in text:
            raise ValueError("This production deployment receipt was already recorded") from exc
        raise
    return get_production_outcome(outcome_id) or {"id": outcome_id}


def _decode(row: Any) -> Dict[str, Any]:
    item = dict(row)
    for raw, clean in (("metrics_json", "metrics"), ("payload_json", "payload")):
        try:
            item[clean] = json.loads(item.pop(raw) or "{}")
        except Exception:
            item[clean] = {}
    return item


def get_production_outcome(outcome_id: str) -> Dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM improvement_production_outcomes WHERE id=?", (outcome_id,)).fetchone()
    return _decode(row) if row else None


def list_production_outcomes(*, project_name: str | None = None, limit: int = 100) -> List[Dict[str, Any]]:
    init_database(); limit = max(1, min(int(limit), 500))
    with get_db() as conn:
        if project_name:
            rows = conn.execute(
                "SELECT * FROM improvement_production_outcomes WHERE project_name=? ORDER BY created_at DESC LIMIT ?",
                (project_name, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM improvement_production_outcomes ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [_decode(row) for row in rows]


def production_learning_statistics(*, project_name: str, limit: int | None = None) -> List[Dict[str, Any]]:
    """Summarize real production outcomes by candidate strategy key.

    Production rollback evidence is intentionally weighted more strongly than local test
    success because the purpose is to stop repeating fixes that look good pre-production
    but prove unsafe after rollout.
    """
    limit = max(1, min(int(limit or getattr(settings, "IMPROVEMENT_PRODUCTION_LEARNING_LOOKBACK", 100)), 1000))
    init_database()
    with get_db() as conn:
        rows = conn.execute(
            """SELECT candidate_strategy_key,status,failure_class,provider,rollout_strategy,created_at
               FROM improvement_production_outcomes
               WHERE project_name=? AND candidate_strategy_key IS NOT NULL
               ORDER BY created_at DESC LIMIT ?""",
            (project_name, limit),
        ).fetchall()
    grouped: dict[str, list[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        item = dict(row); grouped[str(item.get("candidate_strategy_key"))].append(item)
    result: list[Dict[str, Any]] = []
    rollback_penalty = max(0.05, min(float(getattr(settings, "IMPROVEMENT_PRODUCTION_LEARNING_ROLLBACK_PENALTY", 0.35)), 0.6))
    for key, items in grouped.items():
        samples = len(items)
        successes = sum(1 for item in items if item.get("status") == "succeeded")
        rollbacks = sum(1 for item in items if item.get("status") == "rolled_back")
        failures = sum(1 for item in items if item.get("status") in _FAILURE_STATUSES)
        failure_rate = failures / samples if samples else 0.0
        severity = (rollbacks * 1.0 + max(0, failures - rollbacks) * 0.65) / max(1, samples)
        multiplier = max(0.55, 1.0 - min(0.45, severity * rollback_penalty + failure_rate * 0.15))
        if samples >= 3 and failures == 0:
            multiplier = min(1.05, multiplier + 0.03)
        result.append({
            "strategy_key": key,
            "samples": samples,
            "successes": successes,
            "failures": failures,
            "rollbacks": rollbacks,
            "failure_rate": round(failure_rate, 4),
            "production_learning_multiplier": round(multiplier, 4),
            "risk_signal": "high" if rollbacks or failure_rate >= 0.5 else ("medium" if failures else "low"),
        })
    result.sort(key=lambda item: (-item["samples"], item["strategy_key"]))
    return result


def production_learning_summary(project_name: str) -> Dict[str, Any]:
    stats = production_learning_statistics(project_name=project_name)
    outcomes = list_production_outcomes(project_name=project_name, limit=int(getattr(settings, "IMPROVEMENT_PRODUCTION_LEARNING_LOOKBACK", 100)))
    return {
        "project_name": project_name,
        "outcomes_sampled": len(outcomes),
        "succeeded": sum(1 for o in outcomes if o.get("status") == "succeeded"),
        "failed": sum(1 for o in outcomes if o.get("status") in _FAILURE_STATUSES),
        "rolled_back": sum(1 for o in outcomes if o.get("status") == "rolled_back"),
        "strategies": stats,
        "learning_type": "persisted operational outcome memory; not model-weight retraining",
        "backend_can_execute_production": False,
    }
