"""Part 9 scheduler telemetry, persisted alerts, and Prometheus exposition."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from app.config import settings
from app.database import get_db, init_database
from app.improvement_scheduler_store import list_leases, list_scheduler_runs, list_schedules


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def prune_scheduler_observability() -> Dict[str, int]:
    """Bound telemetry and acknowledged-alert growth using configured retention."""
    init_database()
    now = datetime.now(timezone.utc)
    telemetry_cutoff = (now - timedelta(days=max(1, int(settings.IMPROVEMENT_SCHEDULER_TELEMETRY_RETENTION_DAYS)))).isoformat()
    alert_cutoff = (now - timedelta(days=max(1, int(settings.IMPROVEMENT_SCHEDULER_ALERT_RETENTION_DAYS)))).isoformat()
    with get_db() as conn:
        t = conn.execute("DELETE FROM improvement_scheduler_telemetry WHERE created_at < ?", (telemetry_cutoff,))
        a = conn.execute(
            "DELETE FROM improvement_scheduler_alerts WHERE status='acknowledged' AND acknowledged_at IS NOT NULL AND acknowledged_at < ?",
            (alert_cutoff,),
        )
        conn.commit()
    return {"telemetry_deleted": int(t.rowcount or 0), "alerts_deleted": int(a.rowcount or 0)}


def record_scheduler_telemetry(
    *, event_type: str, project_name: str | None = None, schedule_id: str | None = None,
    run_id: str | None = None, duration_ms: float | None = None, attributes: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    init_database()
    item_id = str(uuid.uuid4())
    created_at = _now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO improvement_scheduler_telemetry
               (id, event_type, project_name, schedule_id, run_id, duration_ms, attributes_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (item_id, event_type[:80], project_name, schedule_id, run_id, duration_ms, json.dumps(attributes or {}, ensure_ascii=False, default=str), created_at),
        )
        conn.commit()
    prune_scheduler_observability()
    return {"id": item_id, "event_type": event_type, "created_at": created_at}


def create_scheduler_alert(
    *, project_name: str, severity: str, code: str, message: str,
    schedule_id: str | None = None, run_id: str | None = None, details: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    init_database()
    alert_id = str(uuid.uuid4())
    created_at = _now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO improvement_scheduler_alerts
               (id, project_name, schedule_id, run_id, severity, code, message, details_json, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)""",
            (alert_id, project_name, schedule_id, run_id, severity[:20], code[:80], message[:500], json.dumps(details or {}, ensure_ascii=False, default=str), created_at),
        )
        conn.commit()
    alert = {"id": alert_id, "project_name": project_name, "schedule_id": schedule_id, "run_id": run_id, "severity": severity, "code": code, "message": message, "details": details or {}, "status": "open", "created_at": created_at}
    # Durable outbox: delivery failures never make scheduler alert creation fail.
    try:
        from app.improvement_scheduler_integrations import enqueue_alert_delivery
        enqueue_alert_delivery(alert)
    except Exception:
        pass
    return alert


def list_scheduler_alerts(*, project_name: str | None = None, status: str | None = None, limit: int = 100) -> list[Dict[str, Any]]:
    init_database()
    limit = max(1, min(int(limit), 500))
    with get_db() as conn:
        if project_name and status:
            rows = conn.execute(
                "SELECT * FROM improvement_scheduler_alerts WHERE project_name=? AND status=? ORDER BY created_at DESC LIMIT ?",
                (project_name, status, limit),
            ).fetchall()
        elif project_name:
            rows = conn.execute(
                "SELECT * FROM improvement_scheduler_alerts WHERE project_name=? ORDER BY created_at DESC LIMIT ?",
                (project_name, limit),
            ).fetchall()
        elif status:
            rows = conn.execute(
                "SELECT * FROM improvement_scheduler_alerts WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM improvement_scheduler_alerts ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        try:
            item["details"] = json.loads(item.pop("details_json", "{}"))
        except Exception:
            item["details"] = {}
        output.append(item)
    return output


def acknowledge_scheduler_alert(alert_id: str, *, operator_id: str) -> Dict[str, Any] | None:
    init_database()
    now = _now()
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE improvement_scheduler_alerts SET status='acknowledged', acknowledged_at=?, acknowledged_by=? WHERE id=?",
            (now, operator_id[:120], alert_id),
        )
        conn.commit()
        if not cur.rowcount:
            return None
        row = conn.execute("SELECT * FROM improvement_scheduler_alerts WHERE id=?", (alert_id,)).fetchone()
    item = dict(row)
    try:
        item["details"] = json.loads(item.pop("details_json", "{}"))
    except Exception:
        item["details"] = {}
    return item


def list_scheduler_telemetry(*, project_name: str | None = None, limit: int = 100) -> list[Dict[str, Any]]:
    init_database()
    limit = max(1, min(int(limit), 500))
    with get_db() as conn:
        if project_name:
            rows = conn.execute(
                "SELECT * FROM improvement_scheduler_telemetry WHERE project_name=? ORDER BY created_at DESC LIMIT ?",
                (project_name, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM improvement_scheduler_telemetry ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        try:
            item["attributes"] = json.loads(item.pop("attributes_json", "{}"))
        except Exception:
            item["attributes"] = {}
        output.append(item)
    return output


def scheduler_metrics_snapshot(project_name: str | None = None) -> Dict[str, Any]:
    init_database()
    runs = list_scheduler_runs(project_name=project_name, limit=500)
    schedules = list_schedules(project_name=project_name, limit=500)
    alerts = list_scheduler_alerts(project_name=project_name, limit=500)
    counts: Dict[str, int] = {}
    for run in runs:
        key = str(run.get("status") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    open_alerts = sum(1 for item in alerts if item.get("status") == "open")
    durations = []
    with get_db() as conn:
        if project_name:
            rows = conn.execute(
                "SELECT duration_ms FROM improvement_scheduler_telemetry WHERE project_name=? AND duration_ms IS NOT NULL ORDER BY created_at DESC LIMIT 500",
                (project_name,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT duration_ms FROM improvement_scheduler_telemetry WHERE duration_ms IS NOT NULL ORDER BY created_at DESC LIMIT 500"
            ).fetchall()
    durations = [float(r[0]) for r in rows]
    return {
        "project_name": project_name,
        "schedules_total": len(schedules),
        "schedules_enabled": sum(1 for item in schedules if item.get("enabled")),
        "runs_total_sampled": len(runs),
        "runs_by_status": counts,
        "open_alerts": open_alerts,
        "leases_active": len(list_leases()),
        "run_duration_ms_avg": round(sum(durations) / len(durations), 3) if durations else None,
        "automatic_source_apply_enabled": False,
    }


def prometheus_metrics(project_name: str | None = None) -> str:
    snapshot = scheduler_metrics_snapshot(project_name)
    lines = [
        "# HELP ai_coding_assistant_scheduler_schedules_total Number of scheduler definitions.",
        "# TYPE ai_coding_assistant_scheduler_schedules_total gauge",
        f"ai_coding_assistant_scheduler_schedules_total {snapshot['schedules_total']}",
        "# HELP ai_coding_assistant_scheduler_open_alerts Open scheduler alerts.",
        "# TYPE ai_coding_assistant_scheduler_open_alerts gauge",
        f"ai_coding_assistant_scheduler_open_alerts {snapshot['open_alerts']}",
        "# HELP ai_coding_assistant_scheduler_leases_active Active scheduler leases.",
        "# TYPE ai_coding_assistant_scheduler_leases_active gauge",
        f"ai_coding_assistant_scheduler_leases_active {snapshot['leases_active']}",
        "# HELP ai_coding_assistant_scheduler_runs_total Scheduler runs sampled by status.",
        "# TYPE ai_coding_assistant_scheduler_runs_total gauge",
    ]
    for status, value in sorted(snapshot["runs_by_status"].items()):
        safe = status.replace('"', '')
        lines.append(f'ai_coding_assistant_scheduler_runs_total{{status="{safe}"}} {value}')
    if snapshot["run_duration_ms_avg"] is not None:
        lines += [
            "# HELP ai_coding_assistant_scheduler_run_duration_ms_avg Average persisted scheduler run duration in milliseconds.",
            "# TYPE ai_coding_assistant_scheduler_run_duration_ms_avg gauge",
            f"ai_coding_assistant_scheduler_run_duration_ms_avg {snapshot['run_duration_ms_avg']}",
        ]
    lines.append("# Scheduler source apply is intentionally disabled.")
    return "\n".join(lines) + "\n"
