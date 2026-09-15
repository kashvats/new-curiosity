"""Persistence primitives for the Part 8 dry-run scheduler control plane.

The scheduler is deliberately unable to promote source changes. Schedules only create
observe-only improvement cycles or canary observations. This module stores schedule,
run, lease, control, CI and SLO evidence state in SQLite.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from app.database import get_db, init_database


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().isoformat()


def _loads(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _schedule_row(row: Any) -> Dict[str, Any]:
    item = dict(row)
    item["enabled"] = bool(item.get("enabled"))
    item["require_readiness"] = bool(item.get("require_readiness"))
    item["require_ci_success"] = bool(item.get("require_ci_success"))
    item["require_slo"] = bool(item.get("require_slo"))
    item["bind_ci_to_project_head"] = bool(item.get("bind_ci_to_project_head"))
    item["maintenance_windows"] = _loads(item.pop("maintenance_windows_json", None), [])
    item["request"] = _loads(item.pop("request_json", None), {})
    return item


def create_schedule(
    *, project_name: str, name: str, interval_minutes: int, timezone_name: str = "UTC",
    maintenance_windows: List[Dict[str, Any]] | None = None, mode: str = "observe_propose",
    enabled: bool = True, require_readiness: bool = True, require_ci_success: bool = False,
    require_slo: bool = False, max_runs_per_day: int | None = None,
    request: Dict[str, Any] | None = None, next_run_at: str | None = None, environment: str = "dev",
    ci_branch: str | None = None, ci_commit_sha: str | None = None, bind_ci_to_project_head: bool = False,
) -> Dict[str, Any]:
    init_database()
    schedule_id = str(uuid.uuid4())
    now = _now()
    next_run_at = next_run_at or now
    with get_db() as conn:
        conn.execute(
            """INSERT INTO improvement_schedules
               (id, project_name, name, enabled, mode, interval_minutes, timezone,
                maintenance_windows_json, require_readiness, require_ci_success, require_slo,
                max_runs_per_day, request_json, next_run_at, created_at, updated_at, environment,
                ci_branch, ci_commit_sha, bind_ci_to_project_head)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                schedule_id, project_name, name, 1 if enabled else 0, mode, int(interval_minutes), timezone_name,
                json.dumps(maintenance_windows or [], ensure_ascii=False), 1 if require_readiness else 0,
                1 if require_ci_success else 0, 1 if require_slo else 0, max_runs_per_day,
                json.dumps(request or {}, ensure_ascii=False, default=str), next_run_at, now, now, environment,
                ci_branch, ci_commit_sha, 1 if bind_ci_to_project_head else 0,
            ),
        )
        conn.commit()
    return get_schedule(schedule_id) or {"id": schedule_id}


def update_schedule(schedule_id: str, **changes: Any) -> Dict[str, Any]:
    init_database()
    allowed = {
        "name", "enabled", "mode", "interval_minutes", "timezone", "require_readiness",
        "require_ci_success", "require_slo", "max_runs_per_day", "next_run_at", "last_run_at",
        "environment", "ci_branch", "ci_commit_sha", "bind_ci_to_project_head",
    }
    fields: list[str] = []
    values: list[Any] = []
    for key, value in changes.items():
        if key == "maintenance_windows":
            fields.append("maintenance_windows_json = ?")
            values.append(json.dumps(value or [], ensure_ascii=False))
        elif key == "request":
            fields.append("request_json = ?")
            values.append(json.dumps(value or {}, ensure_ascii=False, default=str))
        elif key in allowed and value is not None:
            fields.append(f"{key} = ?")
            bool_fields = {"enabled", "require_readiness", "require_ci_success", "require_slo", "bind_ci_to_project_head"}
            values.append(1 if key in bool_fields and bool(value) else (0 if key in bool_fields else value))
    fields.append("updated_at = ?")
    values.append(_now())
    values.append(schedule_id)
    with get_db() as conn:
        conn.execute("UPDATE improvement_schedules SET " + ", ".join(fields) + " WHERE id = ?", tuple(values))
        conn.commit()
    return get_schedule(schedule_id) or {}


def delete_schedule(schedule_id: str) -> bool:
    init_database()
    with get_db() as conn:
        cur = conn.execute("DELETE FROM improvement_schedules WHERE id = ?", (schedule_id,))
        conn.commit()
    return bool(cur.rowcount)


def get_schedule(schedule_id: str) -> Dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM improvement_schedules WHERE id = ?", (schedule_id,)).fetchone()
    return _schedule_row(row) if row else None


def list_schedules(*, project_name: str | None = None, enabled_only: bool = False, limit: int = 200) -> List[Dict[str, Any]]:
    init_database()
    limit = max(1, min(int(limit), 500))
    with get_db() as conn:
        if project_name and enabled_only:
            rows = conn.execute(
                "SELECT * FROM improvement_schedules WHERE project_name = ? AND enabled = 1 ORDER BY created_at ASC LIMIT ?",
                (project_name, limit),
            ).fetchall()
        elif project_name:
            rows = conn.execute(
                "SELECT * FROM improvement_schedules WHERE project_name = ? ORDER BY created_at ASC LIMIT ?",
                (project_name, limit),
            ).fetchall()
        elif enabled_only:
            rows = conn.execute(
                "SELECT * FROM improvement_schedules WHERE enabled = 1 ORDER BY created_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM improvement_schedules ORDER BY created_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
    return [_schedule_row(row) for row in rows]


def due_schedules(now_iso: str | None = None, *, limit: int = 50) -> List[Dict[str, Any]]:
    init_database()
    now_iso = now_iso or _now()
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM improvement_schedules
               WHERE enabled = 1 AND (next_run_at IS NULL OR next_run_at <= ?)
               ORDER BY COALESCE(next_run_at, created_at) ASC LIMIT ?""",
            (now_iso, max(1, min(int(limit), 200))),
        ).fetchall()
    return [_schedule_row(row) for row in rows]


def advance_schedule(schedule_id: str, *, interval_minutes: int, ran_at: str | None = None) -> Dict[str, Any]:
    ran_dt = datetime.fromisoformat((ran_at or _now()).replace("Z", "+00:00"))
    if ran_dt.tzinfo is None:
        ran_dt = ran_dt.replace(tzinfo=timezone.utc)
    next_run = ran_dt.astimezone(timezone.utc) + timedelta(minutes=max(1, int(interval_minutes)))
    return update_schedule(schedule_id, last_run_at=ran_dt.astimezone(timezone.utc).isoformat(), next_run_at=next_run.isoformat())


def create_scheduler_run(*, schedule_id: str, project_name: str, mode: str, decision: Dict[str, Any] | None = None) -> Dict[str, Any]:
    init_database()
    run_id = str(uuid.uuid4())
    now = _now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO improvement_scheduler_runs
               (id, schedule_id, project_name, mode, status, decision_json, started_at)
               VALUES (?, ?, ?, ?, 'started', ?, ?)""",
            (run_id, schedule_id, project_name, mode, json.dumps(decision or {}, ensure_ascii=False, default=str), now),
        )
        conn.commit()
    return get_scheduler_run(run_id) or {"id": run_id}


def attach_scheduler_cycle(run_id: str, cycle_id: str) -> Dict[str, Any]:
    init_database()
    with get_db() as conn:
        conn.execute("UPDATE improvement_scheduler_runs SET cycle_id=? WHERE id=?", (cycle_id, run_id))
        conn.commit()
    return get_scheduler_run(run_id) or {}


def finish_scheduler_run(run_id: str, *, status: str, decision: Dict[str, Any] | None = None, cycle_id: str | None = None) -> Dict[str, Any]:
    init_database()
    with get_db() as conn:
        conn.execute(
            """UPDATE improvement_scheduler_runs
               SET status=?, decision_json=?, cycle_id=COALESCE(?, cycle_id), completed_at=? WHERE id=?""",
            (status, json.dumps(decision or {}, ensure_ascii=False, default=str), cycle_id, _now(), run_id),
        )
        conn.commit()
    return get_scheduler_run(run_id) or {}


def _run_row(row: Any) -> Dict[str, Any]:
    item = dict(row)
    item["decision"] = _loads(item.pop("decision_json", None), {})
    return item


def get_scheduler_run(run_id: str) -> Dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM improvement_scheduler_runs WHERE id = ?", (run_id,)).fetchone()
    return _run_row(row) if row else None


def list_scheduler_runs(*, project_name: str | None = None, schedule_id: str | None = None, limit: int = 100) -> List[Dict[str, Any]]:
    init_database()
    limit = max(1, min(int(limit), 500))
    with get_db() as conn:
        if project_name and schedule_id:
            rows = conn.execute(
                "SELECT * FROM improvement_scheduler_runs WHERE project_name = ? AND schedule_id = ? ORDER BY started_at DESC LIMIT ?",
                (project_name, schedule_id, limit),
            ).fetchall()
        elif project_name:
            rows = conn.execute(
                "SELECT * FROM improvement_scheduler_runs WHERE project_name = ? ORDER BY started_at DESC LIMIT ?",
                (project_name, limit),
            ).fetchall()
        elif schedule_id:
            rows = conn.execute(
                "SELECT * FROM improvement_scheduler_runs WHERE schedule_id = ? ORDER BY started_at DESC LIMIT ?",
                (schedule_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM improvement_scheduler_runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [_run_row(row) for row in rows]


def count_scheduler_runs(*, since_iso: str, project_name: str | None = None, schedule_id: str | None = None) -> int:
    init_database()
    with get_db() as conn:
        if project_name and schedule_id:
            row = conn.execute(
                "SELECT COUNT(*) FROM improvement_scheduler_runs WHERE started_at >= ? AND status NOT IN ('blocked', 'skipped') AND project_name = ? AND schedule_id = ?",
                (since_iso, project_name, schedule_id),
            ).fetchone()
        elif project_name:
            row = conn.execute(
                "SELECT COUNT(*) FROM improvement_scheduler_runs WHERE started_at >= ? AND status NOT IN ('blocked', 'skipped') AND project_name = ?",
                (since_iso, project_name),
            ).fetchone()
        elif schedule_id:
            row = conn.execute(
                "SELECT COUNT(*) FROM improvement_scheduler_runs WHERE started_at >= ? AND status NOT IN ('blocked', 'skipped') AND schedule_id = ?",
                (since_iso, schedule_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM improvement_scheduler_runs WHERE started_at >= ? AND status NOT IN ('blocked', 'skipped')",
                (since_iso,),
            ).fetchone()
    return int(row[0] if row else 0)


def get_scheduler_control(scope: str = "global") -> Dict[str, Any]:
    init_database()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM improvement_scheduler_control WHERE scope = ?", (scope,)).fetchone()
    if not row:
        return {"scope": scope, "kill_switch": False, "reason": None, "updated_at": None}
    item = dict(row)
    item["kill_switch"] = bool(item.get("kill_switch"))
    return item


def set_scheduler_kill_switch(*, enabled: bool, reason: str = "", scope: str = "global") -> Dict[str, Any]:
    init_database()
    now = _now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO improvement_scheduler_control(scope, kill_switch, reason, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(scope) DO UPDATE SET kill_switch=excluded.kill_switch, reason=excluded.reason, updated_at=excluded.updated_at""",
            (scope, 1 if enabled else 0, reason[:500], now),
        )
        conn.commit()
    return get_scheduler_control(scope)


def acquire_lease(lease_key: str, *, owner_id: str, ttl_seconds: int) -> Dict[str, Any]:
    """Acquire/replace an expired lease atomically. Returns acquired=False if busy."""
    init_database()
    now = _now_dt()
    expires = now + timedelta(seconds=max(5, int(ttl_seconds)))
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM improvement_scheduler_leases WHERE lease_key = ?", (lease_key,)).fetchone()
        if row:
            current = dict(row)
            try:
                current_expiry = datetime.fromisoformat(str(current["expires_at"]).replace("Z", "+00:00"))
            except Exception:
                current_expiry = now - timedelta(seconds=1)
            if current_expiry > now and current.get("owner_id") != owner_id:
                conn.rollback()
                return {"acquired": False, **current}
        fence_row = conn.execute("SELECT last_token FROM improvement_scheduler_lease_fences WHERE lease_key=?", (lease_key,)).fetchone()
        next_fence = int(fence_row[0] if fence_row else 0) + 1
        conn.execute(
            """INSERT INTO improvement_scheduler_lease_fences(lease_key, last_token) VALUES (?, ?)
               ON CONFLICT(lease_key) DO UPDATE SET last_token=excluded.last_token""",
            (lease_key, next_fence),
        )
        conn.execute(
            """INSERT INTO improvement_scheduler_leases(lease_key, owner_id, acquired_at, heartbeat_at, expires_at, fence_token)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(lease_key) DO UPDATE SET owner_id=excluded.owner_id, acquired_at=excluded.acquired_at,
                   heartbeat_at=excluded.heartbeat_at, expires_at=excluded.expires_at, fence_token=excluded.fence_token""",
            (lease_key, owner_id, now.isoformat(), now.isoformat(), expires.isoformat(), next_fence),
        )
        conn.commit()
    return {"acquired": True, "lease_key": lease_key, "owner_id": owner_id, "expires_at": expires.isoformat(), "fence_token": next_fence}


def heartbeat_lease(lease_key: str, *, owner_id: str, ttl_seconds: int, fence_token: int | None = None) -> bool:
    init_database()
    now = _now_dt()
    expires = now + timedelta(seconds=max(5, int(ttl_seconds)))
    with get_db() as conn:
        if fence_token is None:
            cur = conn.execute(
                "UPDATE improvement_scheduler_leases SET heartbeat_at=?, expires_at=? WHERE lease_key=? AND owner_id=?",
                (now.isoformat(), expires.isoformat(), lease_key, owner_id),
            )
        else:
            cur = conn.execute(
                "UPDATE improvement_scheduler_leases SET heartbeat_at=?, expires_at=? WHERE lease_key=? AND owner_id=? AND fence_token=?",
                (now.isoformat(), expires.isoformat(), lease_key, owner_id, int(fence_token)),
            )
        conn.commit()
    return bool(cur.rowcount)


def release_lease(lease_key: str, *, owner_id: str, fence_token: int | None = None) -> bool:
    init_database()
    with get_db() as conn:
        if fence_token is None:
            cur = conn.execute("DELETE FROM improvement_scheduler_leases WHERE lease_key=? AND owner_id=?", (lease_key, owner_id))
        else:
            cur = conn.execute("DELETE FROM improvement_scheduler_leases WHERE lease_key=? AND owner_id=? AND fence_token=?", (lease_key, owner_id, int(fence_token)))
        conn.commit()
    return bool(cur.rowcount)




def validate_lease(lease_key: str, *, owner_id: str, fence_token: int) -> bool:
    init_database()
    now = _now_dt()
    with get_db() as conn:
        row = conn.execute(
            "SELECT owner_id, fence_token, expires_at FROM improvement_scheduler_leases WHERE lease_key=?", (lease_key,)
        ).fetchone()
    if not row:
        return False
    item = dict(row)
    try:
        expires = datetime.fromisoformat(str(item["expires_at"]).replace("Z", "+00:00"))
    except Exception:
        return False
    return item.get("owner_id") == owner_id and int(item.get("fence_token") or 0) == int(fence_token) and expires > now

def list_leases() -> List[Dict[str, Any]]:
    init_database()
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM improvement_scheduler_leases ORDER BY lease_key").fetchall()
    return [dict(row) for row in rows]


def store_ci_evidence(*, project_name: str, provider: str, status: str, event_type: str = "ci", commit_sha: str | None = None, branch: str | None = None, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    init_database()
    evidence_id = str(uuid.uuid4())
    now = _now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO improvement_ci_evidence
               (id, project_name, provider, event_type, commit_sha, branch, status, payload_json, received_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (evidence_id, project_name, provider[:80], event_type[:80], commit_sha, branch, status, json.dumps(payload or {}, ensure_ascii=False, default=str), now),
        )
        conn.commit()
    return get_ci_evidence(evidence_id) or {"id": evidence_id}


def _ci_row(row: Any) -> Dict[str, Any]:
    item = dict(row)
    item["payload"] = _loads(item.pop("payload_json", None), {})
    return item


def get_ci_evidence(evidence_id: str) -> Dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM improvement_ci_evidence WHERE id=?", (evidence_id,)).fetchone()
    return _ci_row(row) if row else None


def list_ci_evidence(project_name: str, *, limit: int = 50) -> List[Dict[str, Any]]:
    init_database()
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM improvement_ci_evidence WHERE project_name=? ORDER BY received_at DESC LIMIT ?", (project_name, max(1, min(int(limit), 500)))).fetchall()
    return [_ci_row(row) for row in rows]


def store_slo_evidence(*, project_name: str, source: str, availability: float | None = None, error_rate: float | None = None, latency_p95_ms: float | None = None, error_budget_remaining: float | None = None, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    init_database()
    evidence_id = str(uuid.uuid4())
    now = _now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO improvement_slo_evidence
               (id, project_name, source, availability, error_rate, latency_p95_ms, error_budget_remaining, payload_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (evidence_id, project_name, source[:80], availability, error_rate, latency_p95_ms, error_budget_remaining, json.dumps(payload or {}, ensure_ascii=False, default=str), now),
        )
        conn.commit()
    return get_slo_evidence(evidence_id) or {"id": evidence_id}


def _slo_row(row: Any) -> Dict[str, Any]:
    item = dict(row)
    item["payload"] = _loads(item.pop("payload_json", None), {})
    return item


def get_slo_evidence(evidence_id: str) -> Dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM improvement_slo_evidence WHERE id=?", (evidence_id,)).fetchone()
    return _slo_row(row) if row else None


def list_slo_evidence(project_name: str, *, limit: int = 50) -> List[Dict[str, Any]]:
    init_database()
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM improvement_slo_evidence WHERE project_name=? ORDER BY created_at DESC LIMIT ?", (project_name, max(1, min(int(limit), 500)))).fetchall()
    return [_slo_row(row) for row in rows]
