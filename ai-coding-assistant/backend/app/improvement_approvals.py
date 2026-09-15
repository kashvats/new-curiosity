"""Authenticated approval evidence for Part 7 improvement cycles.

Approver credentials are local configuration, not database secrets. The registry is
read from IMPROVEMENT_APPROVER_CREDENTIALS_JSON and approval tokens are never stored.
Example:
{"alice":{"role":"maintainer","token":"..."},"sec":{"role":"security","token":"..."}}
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from app.config import settings
from app.database import get_db, init_database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def approver_registry() -> Dict[str, Dict[str, str]]:
    raw = str(getattr(settings, "IMPROVEMENT_APPROVER_CREDENTIALS_JSON", "{}") or "{}")
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    output: Dict[str, Dict[str, str]] = {}
    if not isinstance(parsed, dict):
        return output
    for ident, value in parsed.items():
        if not isinstance(value, dict):
            continue
        role = str(value.get("role") or "").strip().lower()
        token = str(value.get("token") or "")
        if ident and role and token:
            output[str(ident)] = {"role": role, "token": token}
    return output


def authenticate_approver(approver_id: str, role: str, token: str) -> bool:
    record = approver_registry().get(str(approver_id))
    if not record or record.get("role") != str(role).strip().lower():
        return False
    return hmac.compare_digest(str(record.get("token") or ""), str(token or ""))


def record_cycle_approval(*, cycle_id: str, project_name: str, approver_id: str, role: str, token: str) -> Dict[str, Any]:
    init_database()
    role = str(role).strip().lower()
    if not authenticate_approver(approver_id, role, token):
        raise PermissionError("Invalid approver identity, role, or token")
    approval_id = str(uuid.uuid4())
    now = _now()
    identity_hash = hashlib.sha256(str(approver_id).encode("utf-8")).hexdigest()
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM improvement_approvals WHERE cycle_id = ? AND approver_hash = ? LIMIT 1",
            (cycle_id, identity_hash),
        ).fetchone()
        if existing:
            raise ValueError("Approver has already approved this cycle")
        conn.execute(
            """INSERT INTO improvement_approvals
               (id, cycle_id, project_name, approver_id, approver_hash, role, verified, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
            (approval_id, cycle_id, project_name, str(approver_id), identity_hash, role, now),
        )
        conn.commit()
    return {"id": approval_id, "cycle_id": cycle_id, "project_name": project_name, "approver_id": approver_id, "role": role, "verified": True, "created_at": now}


def list_cycle_approvals(cycle_id: str) -> list[Dict[str, Any]]:
    init_database()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, cycle_id, project_name, approver_id, approver_hash, role, verified, created_at FROM improvement_approvals WHERE cycle_id = ? ORDER BY created_at ASC",
            (cycle_id,),
        ).fetchall()
    return [{**dict(row), "verified": bool(row["verified"])} for row in rows]


def approval_requirement_status(cycle_id: str, policy: Dict[str, Any]) -> Dict[str, Any]:
    approval = policy.get("approval") or {}
    minimum = max(0, int(approval.get("min_verified_approvals") or 0))
    required_roles = {str(v).strip().lower() for v in (approval.get("required_roles") or []) if str(v).strip()}
    distinct_roles = bool(approval.get("distinct_roles", False))
    verified = [row for row in list_cycle_approvals(cycle_id) if row.get("verified")]
    unique: Dict[str, Dict[str, Any]] = {}
    for row in verified:
        unique[str(row.get("approver_hash") or row.get("approver_id"))] = row
    records = list(unique.values())
    roles = {str(row.get("role") or "").lower() for row in records}
    role_ok = required_roles.issubset(roles)
    count_ok = len(records) >= minimum
    distinct_ok = (len(roles) >= minimum) if distinct_roles and minimum else True
    passed = count_ok and role_ok and distinct_ok
    return {
        "passed": passed,
        "minimum": minimum,
        "required_roles": sorted(required_roles),
        "distinct_roles": distinct_roles,
        "verified_approvals": len(records),
        "verified_roles": sorted(roles),
        "approvals": records,
        "reason": None if passed else "approval_quorum_not_satisfied",
    }
