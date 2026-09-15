"""Persistent IDE session state and activity events.

The extension and future web IDE use this store as the audit trail for Ask/Plan/Edit/
Fix/Review/Agent runs. Events are append-only and can be replayed or streamed.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.database import get_db, init_database

TERMINAL_STATUSES = {"completed", "verified", "applied", "failed", "cancelled", "needs_human", "rolled_back"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_ide_session(*, mode: str, project_name: str, task: str, request: Dict[str, Any]) -> Dict[str, Any]:
    init_database()
    session_id = str(uuid.uuid4())
    now = _now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO ide_sessions
               (id, mode, project_name, task, status, request_json, created_at)
               VALUES (?, ?, ?, ?, 'queued', ?, ?)""",
            (session_id, mode, project_name, task, json.dumps(request, ensure_ascii=False, default=str), now),
        )
        conn.commit()
    append_ide_event(session_id, "session_created", stage="queued", message=f"{mode} session queued")
    return get_ide_session(session_id) or {"id": session_id, "status": "queued"}


def append_ide_event(
    session_id: str,
    event_type: str,
    *,
    stage: str | None = None,
    message: str = "",
    payload: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    init_database()
    now = _now()
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO ide_events
               (session_id, event_type, stage, message, payload_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, event_type, stage, message, json.dumps(payload or {}, ensure_ascii=False, default=str), now),
        )
        conn.commit()
        seq = int(cur.lastrowid)
    return {
        "seq": seq,
        "session_id": session_id,
        "event_type": event_type,
        "stage": stage,
        "message": message,
        "payload": payload or {},
        "created_at": now,
    }


def update_ide_session(
    session_id: str,
    *,
    status: str | None = None,
    issue_id: str | None = None,
    result: Dict[str, Any] | None = None,
    error: str | None = None,
    mark_started: bool = False,
    mark_completed: bool = False,
) -> Dict[str, Any]:
    init_database()
    fields: list[str] = []
    values: list[Any] = []
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if issue_id is not None:
        fields.append("issue_id = ?")
        values.append(issue_id)
    if result is not None:
        fields.append("result_json = ?")
        values.append(json.dumps(result, ensure_ascii=False, default=str))
    if error is not None:
        fields.append("error = ?")
        values.append(error)
    if mark_started:
        fields.append("started_at = COALESCE(started_at, ?)")
        values.append(_now())
    if mark_completed:
        fields.append("completed_at = ?")
        values.append(_now())
    if not fields:
        return get_ide_session(session_id) or {}
    values.append(session_id)
    with get_db() as conn:
        conn.execute(f"UPDATE ide_sessions SET {', '.join(fields)} WHERE id = ?", tuple(values))
        conn.commit()
    return get_ide_session(session_id) or {}


def get_ide_session(session_id: str) -> Dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM ide_sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    for raw, clean in (("request_json", "request"), ("result_json", "result")):
        value = item.pop(raw, None)
        try:
            item[clean] = json.loads(value) if value else None
        except Exception:
            item[clean] = None
    return item


def list_ide_events(session_id: str, *, after_seq: int = 0, limit: int = 200) -> List[Dict[str, Any]]:
    init_database()
    limit = max(1, min(int(limit), 1000))
    with get_db() as conn:
        rows = conn.execute(
            """SELECT seq, session_id, event_type, stage, message, payload_json, created_at
               FROM ide_events WHERE session_id = ? AND seq > ? ORDER BY seq ASC LIMIT ?""",
            (session_id, int(after_seq), limit),
        ).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        try:
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
        except Exception:
            item["payload"] = {}
            item.pop("payload_json", None)
        output.append(item)
    return output


def is_terminal_session(session: Dict[str, Any] | None) -> bool:
    return bool(session and session.get("status") in TERMINAL_STATUSES)
