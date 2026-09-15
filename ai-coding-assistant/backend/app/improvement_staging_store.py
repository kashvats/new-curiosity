"""Persistence for Part 13 staging deployments, attestations and release handoffs.

This subsystem may coordinate staging environments only. Production release requests are
human-authorized evidence records; they are not executable production deployments.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.database import get_db, init_database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _loads(value: Any, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except Exception:
        return default


def create_staging_deployment(*, release_id: str, provider: str, environment: str = "staging",
                              manifest: Dict[str, Any] | None = None) -> Dict[str, Any]:
    init_database(); deployment_id = str(uuid.uuid4()); now = _now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO improvement_staging_deployments
               (id,release_id,provider,environment,status,manifest_json,evidence_json,created_at,updated_at)
               VALUES(?,?,?,?, 'created', ?, '{}', ?, ?)""",
            (deployment_id, release_id, provider, environment,
             json.dumps(manifest or {}, ensure_ascii=False, default=str), now, now),
        ); conn.commit()
    return get_staging_deployment(deployment_id) or {"id": deployment_id}


def get_staging_deployment(deployment_id: str) -> Dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM improvement_staging_deployments WHERE id=?", (deployment_id,)).fetchone()
    if not row: return None
    item = dict(row)
    item["manifest"] = _loads(item.pop("manifest_json", None), {})
    item["evidence"] = _loads(item.pop("evidence_json", None), {})
    return item


def list_staging_deployments(*, release_id: str | None = None, limit: int = 100) -> List[Dict[str, Any]]:
    init_database(); limit = max(1, min(int(limit), 500))
    with get_db() as conn:
        if release_id:
            rows = conn.execute("SELECT id FROM improvement_staging_deployments WHERE release_id=? ORDER BY created_at DESC LIMIT ?", (release_id, limit)).fetchall()
        else:
            rows = conn.execute("SELECT id FROM improvement_staging_deployments ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [item for row in rows if (item := get_staging_deployment(row[0]))]


def update_staging_deployment(deployment_id: str, *, status: str | None = None,
                              deployment_ref: str | None = None, preview_url: str | None = None,
                              evidence: Dict[str, Any] | None = None, rolled_back: bool = False) -> Dict[str, Any]:
    current = get_staging_deployment(deployment_id)
    if not current: raise KeyError(deployment_id)
    evidence_json = json.dumps(evidence, ensure_ascii=False, default=str) if evidence is not None else None
    now = _now(); rollback_at = now if rolled_back else None
    with get_db() as conn:
        conn.execute(
            """UPDATE improvement_staging_deployments SET updated_at=?,
                 status=CASE WHEN ? IS NOT NULL THEN ? ELSE status END,
                 deployment_ref=CASE WHEN ? IS NOT NULL THEN ? ELSE deployment_ref END,
                 preview_url=CASE WHEN ? IS NOT NULL THEN ? ELSE preview_url END,
                 evidence_json=CASE WHEN ? IS NOT NULL THEN ? ELSE evidence_json END,
                 rolled_back_at=CASE WHEN ? IS NOT NULL THEN ? ELSE rolled_back_at END
               WHERE id=?""",
            (now, status, status, deployment_ref, deployment_ref, preview_url, preview_url,
             evidence_json, evidence_json, rollback_at, rollback_at, deployment_id),
        ); conn.commit()
    return get_staging_deployment(deployment_id) or current


def store_attestation(*, release_id: str, kind: str, predicate_type: str, digest_sha256: str,
                      statement: Dict[str, Any], signature: str | None = None,
                      signature_algorithm: str | None = None) -> Dict[str, Any]:
    init_database(); attestation_id = str(uuid.uuid4()); now = _now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO improvement_release_attestations
               (id,release_id,kind,predicate_type,digest_sha256,statement_json,signature,signature_algorithm,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (attestation_id, release_id, kind, predicate_type, digest_sha256,
             json.dumps(statement, ensure_ascii=False, sort_keys=True, default=str), signature, signature_algorithm, now),
        ); conn.commit()
    return {"id": attestation_id, "release_id": release_id, "kind": kind, "predicate_type": predicate_type,
            "digest_sha256": digest_sha256, "statement": statement, "signature": signature,
            "signature_algorithm": signature_algorithm, "created_at": now}


def list_attestations(release_id: str) -> List[Dict[str, Any]]:
    init_database()
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM improvement_release_attestations WHERE release_id=? ORDER BY created_at,id", (release_id,)).fetchall()
    out=[]
    for row in rows:
        item=dict(row); item["statement"]=_loads(item.pop("statement_json", None), {}); out.append(item)
    return out


def create_production_release_request(*, release_id: str, requested_by: str, role: str,
                                      evidence_digest: str, request: Dict[str, Any] | None = None) -> Dict[str, Any]:
    init_database(); request_id = str(uuid.uuid4()); now = _now()
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM improvement_production_release_requests WHERE release_id=? AND status='requested' ORDER BY created_at DESC LIMIT 1",
            (release_id,),
        ).fetchone()
        if existing:
            return get_production_release_request(existing[0]) or {"id": existing[0]}
        conn.execute(
            """INSERT INTO improvement_production_release_requests
               (id,release_id,status,requested_by,role,evidence_digest,request_json,created_at,updated_at)
               VALUES(?,?, 'requested', ?, ?, ?, ?, ?, ?)""",
            (request_id, release_id, requested_by[:120], role[:80], evidence_digest,
             json.dumps(request or {}, ensure_ascii=False, default=str), now, now),
        ); conn.commit()
    return get_production_release_request(request_id) or {"id": request_id}


def get_production_release_request(request_id: str) -> Dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row=conn.execute("SELECT * FROM improvement_production_release_requests WHERE id=?", (request_id,)).fetchone()
    if not row: return None
    item=dict(row); item["request"]=_loads(item.pop("request_json", None), {}); return item


def list_production_release_requests(*, release_id: str | None = None, limit: int = 100) -> List[Dict[str, Any]]:
    init_database(); limit=max(1,min(int(limit),500))
    with get_db() as conn:
        if release_id:
            rows=conn.execute("SELECT id FROM improvement_production_release_requests WHERE release_id=? ORDER BY created_at DESC LIMIT ?", (release_id,limit)).fetchall()
        else:
            rows=conn.execute("SELECT id FROM improvement_production_release_requests ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [item for row in rows if (item:=get_production_release_request(row[0]))]
