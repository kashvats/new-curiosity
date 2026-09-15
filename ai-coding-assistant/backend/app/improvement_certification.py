"""Part 16 production-readiness certification.

This module does not deploy anything. It evaluates fresh, operator-recorded hardening
evidence plus production outcome history and emits a signed readiness certificate when
all deterministic gates pass.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from app.config import settings
from app.database import get_db, init_database
from app.improvement_production_feedback import list_production_outcomes
from app.improvement_scheduler_security import record_operator_audit
from app.improvement_secrets import get_secret


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _signing_key() -> str:
    return get_secret("IMPROVEMENT_CERTIFICATION_SIGNING_KEY") or str(settings.IMPROVEMENT_CERTIFICATION_SIGNING_KEY or "")


def _ensure_tables() -> None:
    init_database()
    with get_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS improvement_certification_evidence(
            id TEXT PRIMARY KEY, project_name TEXT NOT NULL, gate TEXT NOT NULL, passed INTEGER NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}', source TEXT NOT NULL, recorded_by TEXT NOT NULL,
            recorded_role TEXT, created_at TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS improvement_certificates(
            id TEXT PRIMARY KEY, project_name TEXT NOT NULL, verdict TEXT NOT NULL,
            report_json TEXT NOT NULL, digest_sha256 TEXT NOT NULL, signature TEXT,
            signature_algorithm TEXT, created_by TEXT NOT NULL, created_at TEXT NOT NULL)""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cert_evidence_project ON improvement_certification_evidence(project_name,gate,created_at)")
        conn.commit()


def capabilities() -> Dict[str, Any]:
    required = [x.strip() for x in str(settings.IMPROVEMENT_CERTIFICATION_REQUIRED_GATES).split(",") if x.strip()]
    return {
        "part": 16,
        "production_readiness_certification": True,
        "signed_certificates": True,
        "signing_configured": bool(_signing_key()),
        "required_gates": required,
        "max_evidence_age_hours": int(settings.IMPROVEMENT_CERTIFICATION_MAX_EVIDENCE_AGE_HOURS),
        "backend_can_execute_production": False,
        "learning_is_operational_memory_not_model_retraining": True,
    }


def record_evidence(*, project_name: str, gate: str, passed: bool, details: Dict[str, Any], source: str, operator: Dict[str, Any]) -> Dict[str, Any]:
    if not operator.get("verified"):
        raise ValueError("Verified operator identity is required for certification evidence")
    _ensure_tables()
    required = {x.strip() for x in str(settings.IMPROVEMENT_CERTIFICATION_REQUIRED_GATES).split(",") if x.strip()}
    if gate not in required:
        raise ValueError("Evidence gate is not part of the configured certification contract")
    evidence_id = str(uuid.uuid4())
    created_at = _now()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO improvement_certification_evidence(id,project_name,gate,passed,details_json,source,recorded_by,recorded_role,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (evidence_id, project_name, gate, 1 if passed else 0, _canonical(details or {}), source[:120], str(operator.get("operator_id") or "unknown")[:120], str(operator.get("role") or "unknown")[:80], created_at),
        )
        conn.commit()
    record_operator_audit(operator=operator, action="production_certification.evidence_recorded", project_name=project_name, metadata={"gate": gate, "passed": bool(passed), "source": source})
    return {"id": evidence_id, "project_name": project_name, "gate": gate, "passed": bool(passed), "details": details or {}, "source": source, "created_at": created_at}


def list_evidence(*, project_name: str, limit: int = 200) -> List[Dict[str, Any]]:
    _ensure_tables(); limit=max(1,min(int(limit),1000))
    with get_db() as conn:
        rows=conn.execute("SELECT * FROM improvement_certification_evidence WHERE project_name=? ORDER BY created_at DESC LIMIT ?",(project_name,limit)).fetchall()
    result=[]
    for row in rows:
        item=dict(row)
        try: item["details"]=json.loads(item.pop("details_json") or "{}")
        except Exception: item["details"]={}
        item["passed"]=bool(item["passed"])
        result.append(item)
    return result


def _latest_gate_evidence(project_name: str) -> Dict[str, Dict[str, Any]]:
    items=list_evidence(project_name=project_name,limit=1000)
    latest: Dict[str, Dict[str, Any]]={}
    for item in items:
        if item["gate"] not in latest:
            latest[item["gate"]]=item
    return latest


def evaluate_readiness(project_name: str) -> Dict[str, Any]:
    required=[x.strip() for x in str(settings.IMPROVEMENT_CERTIFICATION_REQUIRED_GATES).split(",") if x.strip()]
    latest=_latest_gate_evidence(project_name)
    max_age=timedelta(hours=max(1,int(settings.IMPROVEMENT_CERTIFICATION_MAX_EVIDENCE_AGE_HOURS)))
    now=_now_dt(); gates=[]; blockers=[]
    for gate in required:
        evidence=latest.get(gate)
        passed=False; stale=True
        if evidence:
            try:
                created=datetime.fromisoformat(str(evidence["created_at"]).replace("Z","+00:00"))
                if created.tzinfo is None: created=created.replace(tzinfo=timezone.utc)
                stale=now-created.astimezone(timezone.utc) > max_age
            except Exception:
                stale=True
            passed=bool(evidence.get("passed")) and not stale
        if not evidence: blockers.append(f"missing_evidence:{gate}")
        elif stale: blockers.append(f"stale_evidence:{gate}")
        elif not evidence.get("passed"): blockers.append(f"failed_gate:{gate}")
        gates.append({"gate":gate,"passed":passed,"stale":stale,"evidence_id":evidence.get("id") if evidence else None,"created_at":evidence.get("created_at") if evidence else None})

    outcomes=list_production_outcomes(project_name=project_name,limit=100)
    terminal=[o for o in outcomes if o.get("status") in {"succeeded","failed","rolled_back","halted","aborted"}]
    successes=sum(1 for o in terminal if o.get("status")=="succeeded")
    rollbacks=sum(1 for o in terminal if o.get("status")=="rolled_back")
    success_rate=successes/len(terminal) if terminal else 0.0
    rollback_rate=rollbacks/len(terminal) if terminal else 0.0
    if terminal and success_rate < float(settings.IMPROVEMENT_CERTIFICATION_MIN_PRODUCTION_SUCCESS_RATE):
        blockers.append("production_success_rate_below_threshold")
    if terminal and rollback_rate > float(settings.IMPROVEMENT_CERTIFICATION_MAX_ROLLBACK_RATE):
        blockers.append("production_rollback_rate_above_threshold")
    if not _signing_key(): blockers.append("certification_signing_key_not_configured")
    return {
        "project_name":project_name,
        "verdict":"v1_ready" if not blockers else "not_ready",
        "eligible":not blockers,
        "required_gates":gates,
        "production_history":{"samples":len(terminal),"successes":successes,"rollbacks":rollbacks,"success_rate":round(success_rate,4),"rollback_rate":round(rollback_rate,4)},
        "blockers":blockers,
        "evaluated_at":_now(),
        "backend_can_execute_production":False,
    }


def issue_certificate(*, project_name: str, operator: Dict[str, Any], confirm: bool) -> Dict[str, Any]:
    if not confirm: raise ValueError("confirm must be true")
    if not operator.get("verified"):
        raise ValueError("Verified operator identity is required to issue a readiness certificate")
    _ensure_tables(); report=evaluate_readiness(project_name)
    if not report["eligible"]: raise ValueError("Project is not eligible for production-readiness certification")
    key=_signing_key()
    if not key: raise ValueError("Certification signing key is not configured")
    cert_id=str(uuid.uuid4())
    payload={"schema":"ai-coding-assistant.production-readiness-certificate.v1","certificate_id":cert_id,"project_name":project_name,"verdict":"v1_ready","report":report,"issued_by":operator.get("operator_id"),"issued_role":operator.get("role"),"issued_at":_now()}
    digest=_digest(payload)
    signature=hmac.new(key.encode("utf-8"),f"production-readiness-certificate:{digest}".encode("utf-8"),hashlib.sha256).hexdigest()
    with get_db() as conn:
        conn.execute("INSERT INTO improvement_certificates(id,project_name,verdict,report_json,digest_sha256,signature,signature_algorithm,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(cert_id,project_name,"v1_ready",_canonical(payload),digest,signature,"hmac-sha256",str(operator.get("operator_id") or "unknown"),payload["issued_at"]))
        conn.commit()
    record_operator_audit(operator=operator,action="production_certification.issued",project_name=project_name,metadata={"certificate_id":cert_id,"digest":digest})
    return {"id":cert_id,"payload":payload,"digest_sha256":digest,"signature":signature,"signature_algorithm":"hmac-sha256"}


def list_certificates(*, project_name: str | None=None, limit: int=100) -> List[Dict[str,Any]]:
    _ensure_tables(); limit=max(1,min(int(limit),500))
    with get_db() as conn:
        if project_name: rows=conn.execute("SELECT * FROM improvement_certificates WHERE project_name=? ORDER BY created_at DESC LIMIT ?",(project_name,limit)).fetchall()
        else: rows=conn.execute("SELECT * FROM improvement_certificates ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall()
    out=[]
    for row in rows:
        item=dict(row)
        try: item["payload"]=json.loads(item.pop("report_json") or "{}")
        except Exception: item["payload"]={}
        out.append(item)
    return out


def verify_certificate(certificate_id: str) -> Dict[str,Any]:
    certs=list_certificates(limit=500)
    item=next((x for x in certs if x["id"]==certificate_id),None)
    if not item: raise KeyError(certificate_id)
    payload=item.get("payload") or {}; computed=_digest(payload); key=_signing_key()
    expected=hmac.new(key.encode("utf-8"),f"production-readiness-certificate:{computed}".encode("utf-8"),hashlib.sha256).hexdigest() if key else ""
    valid=computed==item.get("digest_sha256") and bool(expected) and hmac.compare_digest(expected,str(item.get("signature") or ""))
    return {"certificate_id":certificate_id,"valid":valid,"digest_matches":computed==item.get("digest_sha256"),"signature_valid":bool(expected) and hmac.compare_digest(expected,str(item.get("signature") or ""))}
