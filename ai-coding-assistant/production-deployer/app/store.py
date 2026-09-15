from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from app.config import settings


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path() -> Path:
    p = Path(str(settings.PRODUCTION_DEPLOYER_DATABASE_PATH))
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@contextmanager
def db():
    conn = sqlite3.connect(str(_path()), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS deployments(
            id TEXT PRIMARY KEY, package_id TEXT NOT NULL, authorization_id TEXT NOT NULL UNIQUE,
            case_id TEXT NOT NULL, release_id TEXT NOT NULL, project_name TEXT NOT NULL, commit_sha TEXT,
            provider TEXT NOT NULL, rollout_strategy TEXT NOT NULL, status TEXT NOT NULL,
            target_json TEXT NOT NULL DEFAULT '{}', package_json TEXT NOT NULL DEFAULT '{}', authorization_json TEXT NOT NULL DEFAULT '{}',
            previous_state_json TEXT NOT NULL DEFAULT '{}', current_stage INTEGER NOT NULL DEFAULT 0,
            created_by TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT, completed_at TEXT,
            failure_class TEXT, last_error TEXT, receipt_json TEXT NOT NULL DEFAULT '{}')""")
        conn.execute("""CREATE TABLE IF NOT EXISTS deployment_observations(
            id TEXT PRIMARY KEY, deployment_id TEXT NOT NULL, stage_index INTEGER,
            metrics_json TEXT NOT NULL DEFAULT '{}', passed INTEGER NOT NULL, blockers_json TEXT NOT NULL DEFAULT '[]',
            created_by TEXT NOT NULL, created_at TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS deployment_events(
            id TEXT PRIMARY KEY, deployment_id TEXT NOT NULL, event_type TEXT NOT NULL,
            operator_id TEXT, role TEXT, payload_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS used_authorizations(
            authorization_id TEXT PRIMARY KEY, deployment_id TEXT NOT NULL, used_at TEXT NOT NULL)""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_deployments_project ON deployments(project_name,created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_deployments_status ON deployments(status,created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_observations_deployment ON deployment_observations(deployment_id,created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_deployment ON deployment_events(deployment_id,created_at)")
        try:
            conn.execute("ALTER TABLE deployment_events ADD COLUMN prev_hash TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE deployment_events ADD COLUMN event_hash TEXT")
        except sqlite3.OperationalError:
            pass
        conn.commit()


def _loads(value: Any, default: Any) -> Any:
    try: return json.loads(value) if value else default
    except Exception: return default


def _decode(row: sqlite3.Row | None) -> Dict[str, Any] | None:
    if not row: return None
    item = dict(row)
    for raw, clean, default in (("target_json","target",{}),("package_json","package",{}),("authorization_json","authorization",{}),("previous_state_json","previous_state",{}),("receipt_json","receipt",{})):
        item[clean] = _loads(item.pop(raw, None), default)
    return item


def create_deployment(*, package: Dict[str,Any], authorization: Dict[str,Any], target: Dict[str,Any], provider: str,
                      strategy: str, created_by: str) -> Dict[str,Any]:
    init_db(); deployment_id=str(uuid.uuid4()); now=_now(); payload=package.get("payload") or {}; auth_payload=authorization.get("payload") or {}
    with db() as conn:
        conn.execute("""INSERT INTO deployments
            (id,package_id,authorization_id,case_id,release_id,project_name,commit_sha,provider,rollout_strategy,status,
             target_json,package_json,authorization_json,created_by,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,'authorized',?,?,?,?,?)""",
            (deployment_id,str(package.get("id")),str(authorization.get("id") or auth_payload.get("authorization_id")),
             str(package.get("case_id") or payload.get("case_id")),str(payload.get("release_id")),str(payload.get("project_name")),
             payload.get("commit_sha"),provider,strategy,json.dumps(target,sort_keys=True,default=str),
             json.dumps(package,sort_keys=True,default=str),json.dumps(authorization,sort_keys=True,default=str),created_by[:120],now))
        conn.commit()
    return get_deployment(deployment_id) or {"id":deployment_id}


def get_deployment(deployment_id: str) -> Dict[str,Any] | None:
    init_db()
    with db() as conn: row=conn.execute("SELECT * FROM deployments WHERE id=?",(deployment_id,)).fetchone()
    return _decode(row)


def list_deployments(*, project_name: str | None=None, limit: int=100) -> List[Dict[str,Any]]:
    init_db(); limit=max(1,min(int(limit),500))
    with db() as conn:
        if project_name: rows=conn.execute("SELECT * FROM deployments WHERE project_name=? ORDER BY created_at DESC LIMIT ?",(project_name,limit)).fetchall()
        else: rows=conn.execute("SELECT * FROM deployments ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall()
    return [_decode(row) for row in rows if row]


def update_deployment(deployment_id: str, *, status: str | None=None, previous_state: Dict[str,Any] | None=None,
                      current_stage: int | None=None, failure_class: str | None=None, last_error: str | None=None,
                      receipt: Dict[str,Any] | None=None, started: bool=False, completed: bool=False) -> Dict[str,Any]:
    current=get_deployment(deployment_id)
    if not current: raise KeyError(deployment_id)
    fields=[]; values=[]
    if status is not None: fields.append("status=?"); values.append(status)
    if previous_state is not None: fields.append("previous_state_json=?"); values.append(json.dumps(previous_state,sort_keys=True,default=str))
    if current_stage is not None: fields.append("current_stage=?"); values.append(int(current_stage))
    if failure_class is not None: fields.append("failure_class=?"); values.append(failure_class)
    if last_error is not None: fields.append("last_error=?"); values.append(last_error[:4000])
    if receipt is not None: fields.append("receipt_json=?"); values.append(json.dumps(receipt,sort_keys=True,default=str))
    if started and not current.get("started_at"): fields.append("started_at=?"); values.append(_now())
    if completed and not current.get("completed_at"): fields.append("completed_at=?"); values.append(_now())
    if not fields: return current
    values.append(deployment_id)
    with db() as conn:
        conn.execute("UPDATE deployments SET "+", ".join(fields)+" WHERE id=?",tuple(values)); conn.commit()
    return get_deployment(deployment_id) or current


def use_authorization(authorization_id: str, deployment_id: str) -> None:
    init_db()
    try:
        with db() as conn:
            conn.execute("INSERT INTO used_authorizations(authorization_id,deployment_id,used_at) VALUES(?,?,?)",(authorization_id,deployment_id,_now())); conn.commit()
    except sqlite3.IntegrityError as exc:
        raise ValueError("Deployment authorization has already been used") from exc


def authorization_used(authorization_id: str) -> bool:
    init_db()
    with db() as conn: row=conn.execute("SELECT 1 FROM used_authorizations WHERE authorization_id=?",(authorization_id,)).fetchone()
    return bool(row)


def record_observation(deployment_id: str, *, stage_index: int | None, metrics: Dict[str,Any], passed: bool,
                       blockers: list[str], created_by: str) -> Dict[str,Any]:
    init_db(); item_id=str(uuid.uuid4()); now=_now()
    with db() as conn:
        conn.execute("INSERT INTO deployment_observations(id,deployment_id,stage_index,metrics_json,passed,blockers_json,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",
                     (item_id,deployment_id,stage_index,json.dumps(metrics,sort_keys=True,default=str),1 if passed else 0,json.dumps(blockers),created_by[:120],now)); conn.commit()
    return {"id":item_id,"deployment_id":deployment_id,"stage_index":stage_index,"metrics":metrics,"passed":passed,"blockers":blockers,"created_at":now}


def list_observations(deployment_id: str, *, limit: int=200) -> List[Dict[str,Any]]:
    init_db()
    with db() as conn: rows=conn.execute("SELECT * FROM deployment_observations WHERE deployment_id=? ORDER BY created_at DESC LIMIT ?",(deployment_id,max(1,min(limit,500)))).fetchall()
    out=[]
    for row in rows:
        item=dict(row); item["metrics"]=_loads(item.pop("metrics_json",None),{}); item["blockers"]=_loads(item.pop("blockers_json",None),[]); item["passed"]=bool(item["passed"]); out.append(item)
    return out


def record_event(deployment_id: str, event_type: str, *, operator: Dict[str,Any] | None=None, payload: Dict[str,Any] | None=None) -> None:
    init_db(); event_id=str(uuid.uuid4()); created_at=_now(); payload_json=json.dumps(payload or {},sort_keys=True,separators=(",",":"),default=str)
    with db() as conn:
        row=conn.execute("SELECT event_hash FROM deployment_events WHERE deployment_id=? ORDER BY created_at DESC,id DESC LIMIT 1",(deployment_id,)).fetchone()
        prev_hash=str(row["event_hash"] or "") if row else ""
        canonical=json.dumps({"id":event_id,"deployment_id":deployment_id,"event_type":event_type,"operator_id":(operator or {}).get("operator_id"),"role":(operator or {}).get("role"),"payload":json.loads(payload_json),"created_at":created_at,"prev_hash":prev_hash},sort_keys=True,separators=(",",":"),default=str)
        event_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        conn.execute("INSERT INTO deployment_events(id,deployment_id,event_type,operator_id,role,payload_json,created_at,prev_hash,event_hash) VALUES(?,?,?,?,?,?,?,?,?)",
                     (event_id,deployment_id,event_type,(operator or {}).get("operator_id"),(operator or {}).get("role"),payload_json,created_at,prev_hash,event_hash)); conn.commit()


def list_events(deployment_id: str, *, limit: int=200) -> List[Dict[str,Any]]:
    init_db()
    with db() as conn: rows=conn.execute("SELECT * FROM deployment_events WHERE deployment_id=? ORDER BY created_at,id LIMIT ?",(deployment_id,max(1,min(limit,500)))).fetchall()
    out=[]
    for row in rows:
        item=dict(row); item["payload"]=_loads(item.pop("payload_json",None),{}); out.append(item)
    return out
