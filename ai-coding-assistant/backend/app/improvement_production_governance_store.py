"""Persistence for Part 14 production release governance.

This module stores governance decisions and signed handoff packages only. It contains
no production deployment executor and stores no production deployment credentials.
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


def create_governance_case(*, production_request_id: str, release_id: str, project_name: str,
                           created_by: str) -> Dict[str, Any]:
    init_database(); now = _now()
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM improvement_production_governance_cases WHERE production_request_id=? ORDER BY created_at DESC LIMIT 1",
            (production_request_id,),
        ).fetchone()
        if row:
            return get_governance_case(row[0]) or {"id": row[0]}
        case_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO improvement_production_governance_cases
               (id,production_request_id,release_id,project_name,status,change_ticket_json,rollout_plan_json,
                created_by,created_at,updated_at)
               VALUES(?,?,?,?, 'draft','{}','{}',?,?,?)""",
            (case_id, production_request_id, release_id, project_name, created_by[:120], now, now),
        )
        conn.commit()
    return get_governance_case(case_id) or {"id": case_id}


def get_governance_case(case_id: str) -> Dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM improvement_production_governance_cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    item["change_ticket"] = _loads(item.pop("change_ticket_json", None), {})
    item["rollout_plan"] = _loads(item.pop("rollout_plan_json", None), {})
    item["artifact_binding"] = _loads(item.pop("artifact_binding_json", None), {})
    return item


def list_governance_cases(*, project_name: str | None = None, status: str | None = None,
                          limit: int = 100) -> List[Dict[str, Any]]:
    init_database(); limit = max(1, min(int(limit), 500))
    with get_db() as conn:
        if project_name and status:
            rows=conn.execute(
                "SELECT id FROM improvement_production_governance_cases WHERE project_name=? AND status=? ORDER BY created_at DESC LIMIT ?",
                (project_name,status,limit),
            ).fetchall()
        elif project_name:
            rows=conn.execute(
                "SELECT id FROM improvement_production_governance_cases WHERE project_name=? ORDER BY created_at DESC LIMIT ?",
                (project_name,limit),
            ).fetchall()
        elif status:
            rows=conn.execute(
                "SELECT id FROM improvement_production_governance_cases WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status,limit),
            ).fetchall()
        else:
            rows=conn.execute(
                "SELECT id FROM improvement_production_governance_cases ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [item for row in rows if (item:=get_governance_case(row[0]))]


def _ensure_mutable(case_id: str) -> Dict[str, Any]:
    case=get_governance_case(case_id)
    if not case: raise KeyError(case_id)
    if case.get("locked_at"):
        raise ValueError("Governance case is locked and immutable")
    if case.get("status") in {"rejected","cancelled"}:
        raise ValueError(f"Governance case is {case.get('status')}")
    return case


def update_case_inputs(case_id: str, *, change_ticket: Dict[str,Any] | None = None,
                       rollout_plan: Dict[str,Any] | None = None, release_train_id: str | None = None,
                       artifact_binding: Dict[str,Any] | None = None, status: str | None = None) -> Dict[str, Any]:
    _ensure_mutable(case_id); now=_now()
    ticket_json=json.dumps(change_ticket,ensure_ascii=False,sort_keys=True,default=str) if change_ticket is not None else None
    plan_json=json.dumps(rollout_plan,ensure_ascii=False,sort_keys=True,default=str) if rollout_plan is not None else None
    artifact_json=json.dumps(artifact_binding,ensure_ascii=False,sort_keys=True,default=str) if artifact_binding is not None else None
    with get_db() as conn:
        conn.execute(
            """UPDATE improvement_production_governance_cases SET updated_at=?,
                 change_ticket_json=CASE WHEN ? IS NOT NULL THEN ? ELSE change_ticket_json END,
                 rollout_plan_json=CASE WHEN ? IS NOT NULL THEN ? ELSE rollout_plan_json END,
                 release_train_id=CASE WHEN ? IS NOT NULL THEN ? ELSE release_train_id END,
                 artifact_binding_json=CASE WHEN ? IS NOT NULL THEN ? ELSE artifact_binding_json END,
                 status=CASE WHEN ? IS NOT NULL THEN ? ELSE status END
               WHERE id=?""",
            (now,ticket_json,ticket_json,plan_json,plan_json,release_train_id,release_train_id,artifact_json,artifact_json,status,status,case_id),
        ); conn.commit()
    return get_governance_case(case_id) or {"id":case_id}


def set_case_status(case_id: str, status: str) -> Dict[str, Any]:
    case=get_governance_case(case_id)
    if not case: raise KeyError(case_id)
    with get_db() as conn:
        conn.execute("UPDATE improvement_production_governance_cases SET status=?,updated_at=? WHERE id=?",(status,_now(),case_id)); conn.commit()
    return get_governance_case(case_id) or case


def add_governance_approval(*, case_id: str, approver_id: str, role: str, decision: str,
                            evidence_digest: str, comment: str | None = None) -> Dict[str, Any]:
    _ensure_mutable(case_id); init_database(); now=_now()
    with get_db() as conn:
        existing=conn.execute(
            """SELECT id FROM improvement_production_governance_approvals
               WHERE case_id=? AND approver_id=? AND evidence_digest=?""",
            (case_id,approver_id,evidence_digest),
        ).fetchone()
        if existing:
            raise ValueError("This operator already decided on the current governance evidence")
        approval_id=str(uuid.uuid4())
        conn.execute(
            """INSERT INTO improvement_production_governance_approvals
               (id,case_id,approver_id,role,decision,evidence_digest,comment,created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (approval_id,case_id,approver_id[:120],role[:80],decision,evidence_digest,(comment or "")[:2000],now),
        ); conn.commit()
    return {"id":approval_id,"case_id":case_id,"approver_id":approver_id,"role":role,"decision":decision,
            "evidence_digest":evidence_digest,"comment":comment or "","created_at":now}


def list_governance_approvals(case_id: str, *, limit: int = 200) -> List[Dict[str, Any]]:
    init_database(); limit=max(1,min(int(limit),500))
    with get_db() as conn:
        rows=conn.execute(
            "SELECT * FROM improvement_production_governance_approvals WHERE case_id=? ORDER BY created_at,id LIMIT ?",
            (case_id,limit),
        ).fetchall()
    return [dict(row) for row in rows]


def create_release_train(*, name: str, window_start: str, window_end: str, timezone_name: str,
                         created_by: str, metadata: Dict[str,Any] | None = None) -> Dict[str, Any]:
    init_database(); train_id=str(uuid.uuid4()); now=_now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO improvement_release_trains
               (id,name,environment,status,window_start,window_end,timezone,metadata_json,created_by,created_at,updated_at)
               VALUES(?,?, 'production','open',?,?,?,?,?,?,?)""",
            (train_id,name[:200],window_start,window_end,timezone_name[:80],
             json.dumps(metadata or {},ensure_ascii=False,default=str),created_by[:120],now,now),
        ); conn.commit()
    return get_release_train(train_id) or {"id":train_id}


def get_release_train(train_id: str) -> Dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row=conn.execute("SELECT * FROM improvement_release_trains WHERE id=?",(train_id,)).fetchone()
    if not row: return None
    item=dict(row); item["metadata"]=_loads(item.pop("metadata_json",None),{}); return item


def list_release_trains(*, status: str | None = None, limit: int = 100) -> List[Dict[str, Any]]:
    init_database(); limit=max(1,min(int(limit),500))
    with get_db() as conn:
        if status:
            rows=conn.execute("SELECT id FROM improvement_release_trains WHERE status=? ORDER BY window_start DESC LIMIT ?",(status,limit)).fetchall()
        else:
            rows=conn.execute("SELECT id FROM improvement_release_trains ORDER BY window_start DESC LIMIT ?",(limit,)).fetchall()
    return [item for row in rows if (item:=get_release_train(row[0]))]


def set_release_train_status(train_id: str, status: str) -> Dict[str, Any]:
    current=get_release_train(train_id)
    if not current: raise KeyError(train_id)
    with get_db() as conn:
        conn.execute("UPDATE improvement_release_trains SET status=?,updated_at=? WHERE id=?",(status,_now(),train_id)); conn.commit()
    return get_release_train(train_id) or current


def lock_governance_case(case_id: str, *, evidence_digest: str, signature: str,
                         signature_algorithm: str, locked_by: str) -> Dict[str, Any]:
    case=_ensure_mutable(case_id); now=_now()
    with get_db() as conn:
        conn.execute(
            """UPDATE improvement_production_governance_cases
               SET status='locked', governance_digest=?, lock_signature=?, lock_signature_algorithm=?,
                   locked_by=?, locked_at=?, updated_at=? WHERE id=?""",
            (evidence_digest,signature,signature_algorithm,locked_by[:120],now,now,case_id),
        ); conn.commit()
    return get_governance_case(case_id) or case


def create_deployment_package(*, case_id: str, digest_sha256: str, signature: str,
                              signature_algorithm: str, payload: Dict[str,Any]) -> Dict[str, Any]:
    case=get_governance_case(case_id)
    if not case: raise KeyError(case_id)
    if not case.get("locked_at"): raise ValueError("Governance case must be locked before package generation")
    init_database(); now=_now()
    with get_db() as conn:
        existing=conn.execute("SELECT id FROM improvement_production_deployment_packages WHERE case_id=? ORDER BY created_at DESC LIMIT 1",(case_id,)).fetchone()
        if existing:
            return get_deployment_package(existing[0]) or {"id":existing[0]}
        package_id=str(uuid.uuid4())
        conn.execute(
            """INSERT INTO improvement_production_deployment_packages
               (id,case_id,digest_sha256,signature,signature_algorithm,payload_json,created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (package_id,case_id,digest_sha256,signature,signature_algorithm,
             json.dumps(payload,ensure_ascii=False,sort_keys=True,default=str),now),
        )
        conn.execute("UPDATE improvement_production_governance_cases SET status='packaged',updated_at=? WHERE id=?",(now,case_id))
        conn.commit()
    return get_deployment_package(package_id) or {"id":package_id}


def get_deployment_package(package_id: str) -> Dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row=conn.execute("SELECT * FROM improvement_production_deployment_packages WHERE id=?",(package_id,)).fetchone()
    if not row: return None
    item=dict(row); item["payload"]=_loads(item.pop("payload_json",None),{}); return item


def list_deployment_packages(*, case_id: str | None = None, limit: int = 100) -> List[Dict[str, Any]]:
    init_database(); limit=max(1,min(int(limit),500))
    with get_db() as conn:
        if case_id:
            rows=conn.execute("SELECT id FROM improvement_production_deployment_packages WHERE case_id=? ORDER BY created_at DESC LIMIT ?",(case_id,limit)).fetchall()
        else:
            rows=conn.execute("SELECT id FROM improvement_production_deployment_packages ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall()
    return [item for row in rows if (item:=get_deployment_package(row[0]))]


def create_deployment_authorization(*, authorization_id: str, package_id: str, case_id: str, project_name: str,
                                    digest_sha256: str, signature: str, signature_algorithm: str,
                                    payload: Dict[str,Any], issued_by: str, expires_at: str) -> Dict[str,Any]:
    init_database(); now=_now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO improvement_production_deployment_authorizations
               (id,package_id,case_id,project_name,digest_sha256,signature,signature_algorithm,payload_json,issued_by,expires_at,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (authorization_id,package_id,case_id,project_name,digest_sha256,signature,signature_algorithm,
             json.dumps(payload,ensure_ascii=False,sort_keys=True,default=str),issued_by[:120],expires_at,now),
        ); conn.commit()
    return get_deployment_authorization(authorization_id) or {"id":authorization_id}


def get_deployment_authorization(authorization_id: str) -> Dict[str,Any] | None:
    init_database()
    with get_db() as conn:
        row=conn.execute("SELECT * FROM improvement_production_deployment_authorizations WHERE id=?",(authorization_id,)).fetchone()
    if not row: return None
    item=dict(row); item["payload"]=_loads(item.pop("payload_json",None),{}); return item


def list_deployment_authorizations(*, package_id: str | None = None, limit: int = 100) -> List[Dict[str,Any]]:
    init_database(); limit=max(1,min(int(limit),500))
    with get_db() as conn:
        if package_id:
            rows=conn.execute("SELECT id FROM improvement_production_deployment_authorizations WHERE package_id=? ORDER BY created_at DESC LIMIT ?",(package_id,limit)).fetchall()
        else:
            rows=conn.execute("SELECT id FROM improvement_production_deployment_authorizations ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall()
    return [item for row in rows if (item:=get_deployment_authorization(row[0]))]


def record_governance_event(*, case_id: str, event_type: str, operator_id: str,
                            role: str, payload: Dict[str,Any] | None = None) -> Dict[str,Any]:
    init_database(); event_id=str(uuid.uuid4()); now=_now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO improvement_production_governance_events
               (id,case_id,event_type,operator_id,role,payload_json,created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (event_id,case_id,event_type[:120],operator_id[:120],role[:80],
             json.dumps(payload or {},ensure_ascii=False,default=str),now),
        ); conn.commit()
    return {"id":event_id,"case_id":case_id,"event_type":event_type,"created_at":now}


def list_governance_events(case_id: str, *, limit: int = 200) -> List[Dict[str,Any]]:
    init_database(); limit=max(1,min(int(limit),500))
    with get_db() as conn:
        rows=conn.execute("SELECT * FROM improvement_production_governance_events WHERE case_id=? ORDER BY created_at,id LIMIT ?",(case_id,limit)).fetchall()
    out=[]
    for row in rows:
        item=dict(row); item["payload"]=_loads(item.pop("payload_json",None),{}); out.append(item)
    return out
