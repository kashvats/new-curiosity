"""Part 9 authentication, replay protection, and operator audit helpers.

These controls authenticate control-plane actions and external evidence. They do not
relax the manual source-apply boundary established by earlier parts.
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


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def signed_webhook_configured() -> bool:
    return bool(str(settings.IMPROVEMENT_EVIDENCE_WEBHOOK_SIGNING_SECRET or ""))


def legacy_webhook_token_configured() -> bool:
    return bool(str(settings.IMPROVEMENT_EVIDENCE_WEBHOOK_TOKEN or ""))


def _parse_signed_timestamp(value: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Missing webhook timestamp")
    try:
        if raw.replace(".", "", 1).isdigit():
            parsed = datetime.fromtimestamp(float(raw), tz=timezone.utc)
        else:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            parsed = parsed.astimezone(timezone.utc)
    except Exception as exc:
        raise ValueError("Invalid webhook timestamp") from exc
    return parsed


def build_evidence_signature(*, payload: Dict[str, Any], timestamp: str, delivery_id: str, secret: str | None = None) -> str:
    """Return the documented `sha256=<hex>` webhook signature.

    Exposed so CI/webhook producers and tests can generate compatible signatures.
    """
    key = str(secret if secret is not None else settings.IMPROVEMENT_EVIDENCE_WEBHOOK_SIGNING_SECRET or "")
    if not key:
        raise ValueError("Webhook signing secret is not configured")
    message = f"{timestamp}.{delivery_id}.{_canonical_json(payload)}".encode("utf-8")
    return "sha256=" + hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_and_record_evidence_delivery(
    *, project_name: str, evidence_type: str, payload: Dict[str, Any], signature: str | None,
    timestamp: str | None, delivery_id: str | None, now: datetime | None = None,
) -> Dict[str, Any]:
    """Verify an HMAC delivery and atomically reject replays.

    The delivery ID is recorded only after timestamp and signature checks pass.
    """
    secret = str(settings.IMPROVEMENT_EVIDENCE_WEBHOOK_SIGNING_SECRET or "")
    if not secret:
        raise ValueError("Signed webhook verification is not configured")
    if not signature or not timestamp or not delivery_id:
        raise ValueError("Signed evidence requires signature, timestamp, and delivery ID")
    delivery_id = str(delivery_id).strip()
    if not delivery_id or len(delivery_id) > 200:
        raise ValueError("Invalid delivery ID")

    signed_at = _parse_signed_timestamp(str(timestamp))
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    skew = abs((current - signed_at).total_seconds())
    max_skew = max(1, int(settings.IMPROVEMENT_EVIDENCE_WEBHOOK_MAX_SKEW_SECONDS))
    if skew > max_skew:
        raise ValueError("Webhook timestamp is outside the allowed replay window")

    expected = build_evidence_signature(payload=payload, timestamp=str(timestamp), delivery_id=delivery_id, secret=secret)
    if not hmac.compare_digest(expected, str(signature)):
        raise ValueError("Invalid webhook signature")

    init_database()
    digest = hashlib.sha256(str(signature).encode("utf-8")).hexdigest()
    with get_db() as conn:
        existing = conn.execute(
            "SELECT delivery_id FROM improvement_webhook_deliveries WHERE delivery_id = ?", (delivery_id,)
        ).fetchone()
        if existing:
            raise ValueError("Webhook delivery has already been processed")
        conn.execute(
            """INSERT INTO improvement_webhook_deliveries
               (delivery_id, project_name, evidence_type, signature_digest, signed_at, received_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (delivery_id, project_name, evidence_type[:40], digest, signed_at.isoformat(), current.isoformat()),
        )
        conn.commit()
    return {
        "authenticated": True,
        "method": "hmac_sha256",
        "delivery_id": delivery_id,
        "signed_at": signed_at.isoformat(),
        "skew_seconds": round(skew, 3),
    }


def _operator_registry() -> Dict[str, Dict[str, str]]:
    raw = str(settings.IMPROVEMENT_OPERATOR_CREDENTIALS_JSON or "{}").strip() or "{}"
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}
    result: Dict[str, Dict[str, str]] = {}
    for operator_id, item in parsed.items():
        if not isinstance(item, dict):
            continue
        token = str(item.get("token") or "")
        role = str(item.get("role") or "operator")
        if operator_id and token:
            result[str(operator_id)] = {"token": token, "role": role}
    return result


def operator_auth_configured() -> bool:
    return bool(_operator_registry())


def verify_operator(operator_id: str | None, token: str | None) -> Dict[str, Any]:
    """Verify an operator when a registry is configured; otherwise return local anonymous context."""
    registry = _operator_registry()
    if not registry:
        return {"verified": False, "operator_id": "local-anonymous", "role": "local", "required": False}
    operator_id = str(operator_id or "").strip()
    token = str(token or "")
    record = registry.get(operator_id)
    if not record or not hmac.compare_digest(record["token"], token):
        raise ValueError("Invalid operator credentials")
    return {"verified": True, "operator_id": operator_id, "role": record["role"], "required": True}


def record_operator_audit(
    *, operator: Dict[str, Any], action: str, project_name: str | None = None,
    schedule_id: str | None = None, metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    init_database()
    audit_id = str(uuid.uuid4())
    created_at = _now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO improvement_operator_audit
               (id, operator_id, role, action, project_name, schedule_id, metadata_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                audit_id, str(operator.get("operator_id") or "unknown")[:120], str(operator.get("role") or "unknown")[:80],
                action[:120], project_name, schedule_id,
                _canonical_json(metadata or {}), created_at,
            ),
        )
        conn.commit()
    return {"id": audit_id, "operator_id": operator.get("operator_id"), "role": operator.get("role"), "action": action, "created_at": created_at}


def list_operator_audit(*, project_name: str | None = None, limit: int = 100) -> list[Dict[str, Any]]:
    init_database()
    limit = max(1, min(int(limit), 500))
    with get_db() as conn:
        if project_name:
            rows = conn.execute(
                "SELECT * FROM improvement_operator_audit WHERE project_name=? ORDER BY created_at DESC LIMIT ?",
                (project_name, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM improvement_operator_audit ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        try:
            item["metadata"] = json.loads(item.pop("metadata_json", "{}"))
        except Exception:
            item["metadata"] = {}
        output.append(item)
    return output
