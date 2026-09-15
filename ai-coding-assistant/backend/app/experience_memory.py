"""Contextual engineering experience memory for v1.1.

Unlike a global "strategy failed" counter, this records the problem context, files,
strategy, outcome and failure class. Retrieval is deterministic and project-scoped.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import uuid
from typing import Any, Dict, Iterable, List

from app.config import settings
from app.database import get_db, init_database, get_db_path

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]{2,}")
_STOP = {"the", "and", "for", "with", "from", "this", "that", "into", "make", "fix", "change", "update", "issue", "file", "code"}
_SCHEMA_DB_PATH: str | None = None


def _ensure_schema() -> None:
    global _SCHEMA_DB_PATH
    current = get_db_path()
    if _SCHEMA_DB_PATH != current:
        init_database()
        _SCHEMA_DB_PATH = current


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _terms(text: str) -> set[str]:
    return {m.group(0).lower() for m in _WORD_RE.finditer(text or "") if m.group(0).lower() not in _STOP}


def _fingerprint(project_name: str, task: str, strategy: str, outcome: str, failure_class: str | None, files: Iterable[str]) -> str:
    payload = {
        "project": project_name,
        "task_terms": sorted(_terms(task)),
        "strategy": strategy or "",
        "outcome": outcome,
        "failure_class": failure_class or "",
        "files": sorted(str(x).replace("\\", "/") for x in files if str(x)),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def record_experience(
    *,
    project_name: str,
    issue_id: str,
    task: str,
    strategy: str,
    outcome: str,
    files: Iterable[str] = (),
    failure_class: str | None = None,
    lesson: str = "",
    validation_status: str = "",
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    _ensure_schema()
    files_list = sorted({str(x).replace("\\", "/") for x in files if str(x)})
    fp = _fingerprint(project_name, task, strategy, outcome, failure_class, files_list)
    now = _now()
    exp_id = str(uuid.uuid4())
    with get_db() as conn:
        # Atomic UPSERT: concurrent repair cycles can record the same contextual
        # experience without racing a SELECT-then-INSERT sequence.
        conn.execute(
            """INSERT INTO engineering_experiences
               (id,project_name,issue_id,fingerprint,task,task_terms_json,strategy,outcome,failure_class,
                files_json,lesson,validation_status,metadata_json,occurrence_count,created_at,last_seen_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(fingerprint) DO UPDATE SET
                 issue_id=excluded.issue_id,
                 lesson=excluded.lesson,
                 validation_status=excluded.validation_status,
                 metadata_json=excluded.metadata_json,
                 occurrence_count=engineering_experiences.occurrence_count + 1,
                 last_seen_at=excluded.last_seen_at""",
            (
                exp_id, project_name, issue_id, fp, task[:8000], json.dumps(sorted(_terms(task))), strategy or "",
                outcome, failure_class, json.dumps(files_list), (lesson or "")[:4000], validation_status or "",
                json.dumps(metadata or {}, default=str), 1, now, now,
            ),
        )
        row = conn.execute("SELECT id FROM engineering_experiences WHERE fingerprint=?", (fp,)).fetchone()
        conn.commit()
        if row:
            exp_id = str(row["id"])
    return {"id": exp_id, "fingerprint": fp}


def _decode(row: Any) -> Dict[str, Any]:
    item = dict(row)
    for raw, clean, fallback in (
        ("task_terms_json", "task_terms", []),
        ("files_json", "files", []),
        ("metadata_json", "metadata", {}),
    ):
        try:
            item[clean] = json.loads(item.pop(raw) or json.dumps(fallback))
        except Exception:
            item[clean] = fallback
    return item


def search_experiences(
    *,
    project_name: str,
    task: str,
    files: Iterable[str] = (),
    limit: int = 5,
) -> List[Dict[str, Any]]:
    _ensure_schema()
    query_terms = _terms(task)
    query_files = {str(x).replace("\\", "/") for x in files if str(x)}
    history_limit = max(20, min(int(getattr(settings, "V11_EXPERIENCE_HISTORY_LIMIT", 300)), 2000))
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM engineering_experiences WHERE project_name=? ORDER BY last_seen_at DESC LIMIT ?",
            (project_name, history_limit),
        ).fetchall()
    scored: list[tuple[float, Dict[str, Any]]] = []
    for row in rows:
        item = _decode(row)
        exp_terms = set(item.get("task_terms") or [])
        overlap = len(query_terms & exp_terms)
        union = max(1, len(query_terms | exp_terms))
        term_score = overlap / union
        exp_files = set(item.get("files") or [])
        file_overlap = len(query_files & exp_files) / max(1, len(query_files | exp_files)) if query_files or exp_files else 0.0
        recurrence = min(0.12, max(0, int(item.get("occurrence_count") or 1) - 1) * 0.02)
        failure_weight = 0.08 if item.get("outcome") in {"failed", "rolled_back", "gate_failed"} else 0.03
        score = term_score * 0.68 + file_overlap * 0.24 + recurrence + failure_weight
        if overlap == 0 and file_overlap == 0:
            continue
        item["relevance_score"] = round(score, 4)
        scored.append((score, item))
    # Prefer stronger semantic/file relevance, then the most recently observed
    # experience when scores tie. ISO-8601 UTC timestamps sort chronologically.
    scored.sort(
        key=lambda pair: (pair[0], str(pair[1].get("last_seen_at") or "")),
        reverse=True,
    )
    return [item for _, item in scored[: max(1, min(int(limit), 20))]]


def format_experiences_for_prompt(experiences: List[Dict[str, Any]], *, max_chars: int = 7000) -> str:
    if not experiences:
        return "No closely related prior engineering experiences were found."
    lines = ["Relevant prior engineering experiences (use as evidence, not absolute rules):"]
    for item in experiences:
        lines.extend([
            f"- outcome={item.get('outcome')} strategy={item.get('strategy') or 'unknown'} failure={item.get('failure_class') or 'none'} occurrences={item.get('occurrence_count', 1)} relevance={item.get('relevance_score')}",
            f"  task={str(item.get('task') or '')[:500]}",
            f"  files={', '.join((item.get('files') or [])[:8])}",
            f"  lesson={str(item.get('lesson') or '')[:700]}",
        ])
    return "\n".join(lines)[:max_chars]
