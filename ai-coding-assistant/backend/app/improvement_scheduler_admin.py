"""Part 10 scheduler retention, compaction and disaster-recovery drill helpers."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

from app.config import settings
from app.database import get_db, get_db_path, init_database
from app.improvement_scheduler_observability import prune_scheduler_observability
from app.improvement_scheduler_tracing import prune_traces


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def retention_preview() -> Dict[str, Any]:
    init_database(); now = datetime.now(timezone.utc)
    cutoffs = {
        "webhook_deliveries": (now - timedelta(days=max(1, int(getattr(settings, "IMPROVEMENT_WEBHOOK_DELIVERY_RETENTION_DAYS", 30))))).isoformat(),
        "operator_audit": (now - timedelta(days=max(1, int(getattr(settings, "IMPROVEMENT_OPERATOR_AUDIT_RETENTION_DAYS", 180))))).isoformat(),
        "scheduler_runs": (now - timedelta(days=max(1, int(getattr(settings, "IMPROVEMENT_SCHEDULER_RUN_RETENTION_DAYS", 90))))).isoformat(),
        "integration_deliveries": (now - timedelta(days=max(1, int(getattr(settings, "IMPROVEMENT_INTEGRATION_DELIVERY_RETENTION_DAYS", 30))))).isoformat(),
        "status_publications": (now - timedelta(days=max(1, int(getattr(settings, "IMPROVEMENT_INTEGRATION_DELIVERY_RETENTION_DAYS", 30))))).isoformat(),
    }
    queries = {
        "webhook_deliveries": ("SELECT COUNT(*) FROM improvement_webhook_deliveries WHERE received_at < ?", cutoffs["webhook_deliveries"]),
        "operator_audit": ("SELECT COUNT(*) FROM improvement_operator_audit WHERE created_at < ?", cutoffs["operator_audit"]),
        "scheduler_runs": ("SELECT COUNT(*) FROM improvement_scheduler_runs WHERE completed_at IS NOT NULL AND completed_at < ?", cutoffs["scheduler_runs"]),
        "integration_deliveries": ("SELECT COUNT(*) FROM improvement_scheduler_deliveries WHERE status='delivered' AND delivered_at IS NOT NULL AND delivered_at < ?", cutoffs["integration_deliveries"]),
        "status_publications": ("SELECT COUNT(*) FROM improvement_scheduler_status_publications WHERE status='delivered' AND delivered_at IS NOT NULL AND delivered_at < ?", cutoffs["status_publications"]),
    }
    counts = {}
    with get_db() as conn:
        for key, (sql, cutoff) in queries.items():
            counts[key] = int(conn.execute(sql, (cutoff,)).fetchone()[0])
    db_path = Path(get_db_path())
    return {"counts": counts, "cutoffs": cutoffs, "database_bytes": db_path.stat().st_size if db_path.exists() else 0, "destructive": False}


def run_retention_compaction(*, vacuum: bool = False) -> Dict[str, Any]:
    preview = retention_preview(); deleted: Dict[str, int] = {}
    with get_db() as conn:
        cur = conn.execute("DELETE FROM improvement_webhook_deliveries WHERE received_at < ?", (preview["cutoffs"]["webhook_deliveries"],)); deleted["webhook_deliveries"] = cur.rowcount or 0
        cur = conn.execute("DELETE FROM improvement_operator_audit WHERE created_at < ?", (preview["cutoffs"]["operator_audit"],)); deleted["operator_audit"] = cur.rowcount or 0
        cur = conn.execute("DELETE FROM improvement_scheduler_runs WHERE completed_at IS NOT NULL AND completed_at < ?", (preview["cutoffs"]["scheduler_runs"],)); deleted["scheduler_runs"] = cur.rowcount or 0
        cur = conn.execute("DELETE FROM improvement_scheduler_deliveries WHERE status='delivered' AND delivered_at IS NOT NULL AND delivered_at < ?", (preview["cutoffs"]["integration_deliveries"],)); deleted["integration_deliveries"] = cur.rowcount or 0
        cur = conn.execute("DELETE FROM improvement_scheduler_status_publications WHERE status='delivered' AND delivered_at IS NOT NULL AND delivered_at < ?", (preview["cutoffs"]["status_publications"],)); deleted["status_publications"] = cur.rowcount or 0
        conn.commit()
    deleted.update(prune_scheduler_observability())
    deleted["scheduler_traces"] = prune_traces()
    if vacuum:
        conn = sqlite3.connect(get_db_path(), timeout=60)
        try: conn.execute("VACUUM")
        finally: conn.close()
    return {"deleted": deleted, "vacuum": bool(vacuum), "database_bytes_after": Path(get_db_path()).stat().st_size, "automatic_source_apply_enabled": False}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dr_root() -> Path:
    root = Path(str(getattr(settings, "IMPROVEMENT_SCHEDULER_DR_DIR", "../data/scheduler-drills") or "../data/scheduler-drills"))
    if not root.is_absolute():
        root = Path(__file__).parent.parent / root
    root.mkdir(parents=True, exist_ok=True)
    return root


def rotate_disaster_recovery_backups(*, keep: int | None = None) -> Dict[str, Any]:
    keep = max(1, int(keep if keep is not None else getattr(settings, "IMPROVEMENT_SCHEDULER_DR_BACKUP_KEEP", 10)))
    root = _dr_root()
    backups = sorted(root.glob("scheduler-drill-*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = []
    for path in backups[keep:]:
        try:
            path.unlink(); removed.append(str(path))
        except OSError:
            pass
    return {"keep": keep, "existing": len(backups), "removed": removed, "automatic_source_apply_enabled": False}


def _drill_result(drill_id: str) -> Dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row = conn.execute("SELECT result_json FROM improvement_scheduler_dr_drills WHERE id=?", (drill_id,)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0] or "{}")
    except Exception:
        return {}


def verify_disaster_recovery_restore(drill_id: str) -> Dict[str, Any]:
    result = _drill_result(drill_id)
    if result is None:
        raise KeyError(drill_id)
    backup = Path(str(result.get("backup_path") or ""))
    if not backup.is_file():
        return {"drill_id": drill_id, "verified": False, "reason": "backup_missing", "backup_path": str(backup)}
    expected_sha = str(result.get("sha256") or "")
    actual_sha = _sha256(backup)
    conn = sqlite3.connect(str(backup), timeout=60)
    try:
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        required = {"improvement_schedules", "improvement_scheduler_runs", "improvement_scheduler_control", "improvement_operator_audit"}
        missing = sorted(required - tables)
        schedule_count = int(conn.execute("SELECT COUNT(*) FROM improvement_schedules").fetchone()[0]) if "improvement_schedules" in tables else 0
    finally:
        conn.close()
    verified = integrity.lower() == "ok" and not missing and (not expected_sha or expected_sha == actual_sha) and schedule_count == int(result.get("schedule_count") or 0)
    return {
        "drill_id": drill_id, "verified": verified, "integrity_check": integrity, "missing_tables": missing,
        "sha256_matches": (not expected_sha or expected_sha == actual_sha), "schedule_count": schedule_count,
        "expected_schedule_count": int(result.get("schedule_count") or 0), "backup_path": str(backup),
        "automatic_source_apply_enabled": False,
    }


def run_disaster_recovery_drill() -> Dict[str, Any]:
    init_database()
    root = _dr_root()
    drill_id = str(uuid.uuid4())
    backup = root / f"scheduler-drill-{drill_id}.sqlite3"
    source = sqlite3.connect(get_db_path(), timeout=60)
    target = sqlite3.connect(str(backup), timeout=60)
    try:
        source.backup(target)
    finally:
        target.close(); source.close()
    verify = sqlite3.connect(str(backup), timeout=60)
    try:
        integrity = str(verify.execute("PRAGMA integrity_check").fetchone()[0])
        tables = {row[0] for row in verify.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        required = {"improvement_schedules", "improvement_scheduler_runs", "improvement_scheduler_control", "improvement_operator_audit"}
        missing = sorted(required - tables)
        schedule_count = int(verify.execute("SELECT COUNT(*) FROM improvement_schedules").fetchone()[0]) if "improvement_schedules" in tables else 0
    finally:
        verify.close()
    passed = integrity.lower() == "ok" and not missing
    result = {
        "id": drill_id, "status": "passed" if passed else "failed", "integrity_check": integrity,
        "missing_tables": missing, "schedule_count": schedule_count, "backup_path": str(backup),
        "backup_bytes": backup.stat().st_size, "sha256": _sha256(backup), "created_at": _now(),
        "automatic_source_apply_enabled": False,
    }
    with get_db() as conn:
        conn.execute("INSERT INTO improvement_scheduler_dr_drills(id,status,result_json,created_at) VALUES(?,?,?,?)", (drill_id, result["status"], json.dumps(result, ensure_ascii=False, default=str), result["created_at"]))
        conn.commit()
    result["rotation"] = rotate_disaster_recovery_backups()
    return result


def list_disaster_recovery_drills(*, limit: int = 50) -> list[Dict[str, Any]]:
    init_database(); limit = max(1, min(int(limit), 200))
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM improvement_scheduler_dr_drills ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        try: item["result"] = json.loads(item.pop("result_json", "{}"))
        except Exception: item["result"] = {}
        out.append(item)
    return out
