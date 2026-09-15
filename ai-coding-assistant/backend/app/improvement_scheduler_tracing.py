"""Structured scheduler tracing persisted locally for Part 11."""
from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator

from app.config import settings
from app.database import get_db, init_database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_trace_id() -> str:
    return uuid.uuid4().hex


def record_span(*, trace_id: str, name: str, project_name: str | None = None,
                schedule_id: str | None = None, run_id: str | None = None,
                parent_span_id: str | None = None, status: str = "ok",
                duration_ms: float | None = None, attributes: Dict[str, Any] | None = None,
                span_id: str | None = None) -> Dict[str, Any]:
    init_database()
    item = {
        "id": str(uuid.uuid4()), "trace_id": trace_id, "span_id": span_id or uuid.uuid4().hex[:16],
        "parent_span_id": parent_span_id, "name": name, "project_name": project_name,
        "schedule_id": schedule_id, "run_id": run_id, "status": status,
        "duration_ms": duration_ms, "attributes": attributes or {}, "created_at": _now(),
    }
    with get_db() as conn:
        conn.execute(
            """INSERT INTO improvement_scheduler_traces
               (id,trace_id,span_id,parent_span_id,name,project_name,schedule_id,run_id,status,duration_ms,attributes_json,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (item["id"], item["trace_id"], item["span_id"], item["parent_span_id"], item["name"],
             item["project_name"], item["schedule_id"], item["run_id"], item["status"], item["duration_ms"],
             json.dumps(item["attributes"], ensure_ascii=False, default=str), item["created_at"]),
        )
        conn.commit()
    return item


@contextmanager
def scheduler_span(*, trace_id: str, name: str, project_name: str | None = None,
                   schedule_id: str | None = None, run_id: str | None = None,
                   parent_span_id: str | None = None, attributes: Dict[str, Any] | None = None) -> Iterator[str]:
    started = time.perf_counter()
    span_id = uuid.uuid4().hex[:16]
    status = "ok"
    extra = dict(attributes or {})
    try:
        yield span_id
    except Exception as exc:
        status = "error"
        extra["error_type"] = type(exc).__name__
        extra["error"] = str(exc)[:500]
        raise
    finally:
        record_span(trace_id=trace_id, span_id=span_id, parent_span_id=parent_span_id, name=name,
                    project_name=project_name, schedule_id=schedule_id, run_id=run_id, status=status,
                    duration_ms=(time.perf_counter() - started) * 1000.0, attributes=extra)


def list_traces(*, project_name: str | None = None, run_id: str | None = None,
                trace_id: str | None = None, limit: int = 200) -> list[Dict[str, Any]]:
    init_database(); limit = max(1, min(int(limit), 1000))
    where, values = [], []
    if project_name: where.append("project_name=?"); values.append(project_name)
    if run_id: where.append("run_id=?"); values.append(run_id)
    if trace_id: where.append("trace_id=?"); values.append(trace_id)
    sql = "SELECT * FROM improvement_scheduler_traces"
    if where: sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT ?"; values.append(limit)
    with get_db() as conn:
        rows = conn.execute(sql, values).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        try: item["attributes"] = json.loads(item.pop("attributes_json", "{}"))
        except Exception: item["attributes"] = {}
        out.append(item)
    return out


def prune_traces() -> int:
    days = max(1, int(getattr(settings, "IMPROVEMENT_SCHEDULER_TRACE_RETENTION_DAYS", 14)))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with get_db() as conn:
        cur = conn.execute("DELETE FROM improvement_scheduler_traces WHERE created_at < ?", (cutoff,))
        conn.commit()
        return int(cur.rowcount or 0)
