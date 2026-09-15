"""Persistent project change/test timeline used by tests and agent workflows."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.database import get_db, init_database


def create_timeline_event(
    *,
    event_type: str,
    title: str,
    description: str | None = None,
    related_test_run_id: str | None = None,
    related_snapshot_id: str | None = None,
    related_issue_id: str | None = None,
    status: str | None = None,
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    init_database()
    event_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO change_timeline
               (id, event_type, title, description, related_test_run_id,
                related_snapshot_id, related_issue_id, status, metadata_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id, event_type, title, description, related_test_run_id,
                related_snapshot_id, related_issue_id, status,
                json.dumps(metadata or {}, ensure_ascii=False), created_at,
            ),
        )
        conn.commit()
    return {"id": event_id, "event_type": event_type, "title": title, "status": status, "created_at": created_at}


def list_timeline_events(limit: int = 100) -> List[Dict[str, Any]]:
    init_database()
    safe_limit = max(1, min(int(limit), 500))
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM change_timeline ORDER BY created_at DESC LIMIT ?", (safe_limit,)
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        except Exception:
            item["metadata"] = {}
        result.append(item)
    return result
