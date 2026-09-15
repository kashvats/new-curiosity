"""Persistence for Part 12 candidate-to-staging release orchestration.

The release subsystem never promotes to production. It records immutable-ish evidence
about an isolated candidate workspace and allows an authenticated operator to mark a
fully-gated candidate as staging-ready.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

from app.database import get_db, init_database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _loads(value: Any, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except Exception:
        return default


def create_release_candidate(
    *, project_name: str, issue_id: str, commit_sha: str | None = None,
    scm_provider: str | None = None, scm_target: str | None = None,
    request: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    init_database(); release_id = str(uuid.uuid4()); now = _now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO improvement_release_candidates
               (id, project_name, issue_id, commit_sha, scm_provider, scm_target, status,
                request_json, evidence_bundle_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'created', ?, '{}', ?, ?)""",
            (release_id, project_name, issue_id, commit_sha, scm_provider, scm_target,
             json.dumps(request or {}, ensure_ascii=False, default=str), now, now),
        )
        conn.commit()
    return get_release_candidate(release_id) or {"id": release_id}


def get_release_candidate(release_id: str) -> Dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM improvement_release_candidates WHERE id=?", (release_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    item["request"] = _loads(item.pop("request_json", None), {})
    item["evidence_bundle"] = _loads(item.pop("evidence_bundle_json", None), {})
    item["production_promotion_allowed"] = bool(item.get("production_promotion_allowed"))
    return item


def list_release_candidates(*, project_name: str | None = None, status: str | None = None, limit: int = 100) -> List[Dict[str, Any]]:
    init_database(); clauses: list[str] = []; args: list[Any] = []
    if project_name:
        clauses.append("project_name=?"); args.append(project_name)
    if status:
        clauses.append("status=?"); args.append(status)
    query = "SELECT id FROM improvement_release_candidates"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at DESC LIMIT ?"; args.append(max(1, min(int(limit), 500)))
    with get_db() as conn:
        rows = conn.execute(query, tuple(args)).fetchall()
    return [item for row in rows if (item := get_release_candidate(row[0]))]


def update_release_candidate(release_id: str, *, status: str | None = None, workspace_path: str | None = None,
                             evidence_bundle: Dict[str, Any] | None = None, staging_ready: bool = False,
                             failure_reason: str | None = None) -> Dict[str, Any]:
    current = get_release_candidate(release_id)
    if not current:
        raise KeyError(release_id)
    now = _now()
    bundle_json = json.dumps(evidence_bundle, ensure_ascii=False, default=str) if evidence_bundle is not None else None
    ready_at = now if staging_ready else None
    with get_db() as conn:
        conn.execute(
            """UPDATE improvement_release_candidates SET
                 updated_at=?,
                 status=CASE WHEN ? IS NOT NULL THEN ? ELSE status END,
                 workspace_path=CASE WHEN ? IS NOT NULL THEN ? ELSE workspace_path END,
                 evidence_bundle_json=CASE WHEN ? IS NOT NULL THEN ? ELSE evidence_bundle_json END,
                 staging_ready_at=CASE WHEN ? IS NOT NULL THEN ? ELSE staging_ready_at END,
                 failure_reason=CASE WHEN ? IS NOT NULL THEN ? ELSE failure_reason END
               WHERE id=?""",
            (now, status, status, workspace_path, workspace_path, bundle_json, bundle_json,
             ready_at, ready_at, failure_reason, failure_reason[:1000] if failure_reason is not None else None, release_id),
        )
        conn.commit()
    return get_release_candidate(release_id) or current


def store_release_check(release_id: str, *, check_type: str, status: str, details: Dict[str, Any] | None = None) -> Dict[str, Any]:
    init_database(); check_id = str(uuid.uuid4()); now = _now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO improvement_release_checks(id,release_id,check_type,status,details_json,created_at)
               VALUES(?,?,?,?,?,?)""",
            (check_id, release_id, check_type, status, json.dumps(details or {}, ensure_ascii=False, default=str), now),
        ); conn.commit()
    return {"id": check_id, "release_id": release_id, "check_type": check_type, "status": status, "details": details or {}, "created_at": now}


def list_release_checks(release_id: str) -> List[Dict[str, Any]]:
    init_database()
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM improvement_release_checks WHERE release_id=? ORDER BY created_at,id", (release_id,)).fetchall()
    out = []
    for row in rows:
        item = dict(row); item["details"] = _loads(item.pop("details_json", None), {}); out.append(item)
    return out


def store_release_artifact(release_id: str, *, kind: str, name: str, digest_sha256: str,
                           path: str | None = None, signature: str | None = None,
                           signature_algorithm: str | None = None, metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
    init_database(); artifact_id = str(uuid.uuid4()); now = _now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO improvement_release_artifacts
               (id,release_id,kind,name,digest_sha256,path,signature,signature_algorithm,metadata_json,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (artifact_id, release_id, kind, name, digest_sha256, path, signature, signature_algorithm,
             json.dumps(metadata or {}, ensure_ascii=False, default=str), now),
        ); conn.commit()
    return {"id": artifact_id, "release_id": release_id, "kind": kind, "name": name, "digest_sha256": digest_sha256,
            "path": path, "signature": signature, "signature_algorithm": signature_algorithm, "metadata": metadata or {}, "created_at": now}


def list_release_artifacts(release_id: str) -> List[Dict[str, Any]]:
    init_database()
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM improvement_release_artifacts WHERE release_id=? ORDER BY created_at,id", (release_id,)).fetchall()
    out = []
    for row in rows:
        item = dict(row); item["metadata"] = _loads(item.pop("metadata_json", None), {}); out.append(item)
    return out


def create_preview_environment(release_id: str, *, provider: str, preview_url: str | None, status: str,
                               expires_at: str | None = None, metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
    init_database(); preview_id = str(uuid.uuid4()); now = _now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO improvement_preview_environments
               (id,release_id,provider,preview_url,status,expires_at,metadata_json,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (preview_id, release_id, provider, preview_url, status, expires_at,
             json.dumps(metadata or {}, ensure_ascii=False, default=str), now, now),
        ); conn.commit()
    return get_preview_environment(preview_id) or {"id": preview_id}


def get_preview_environment(preview_id: str) -> Dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM improvement_preview_environments WHERE id=?", (preview_id,)).fetchone()
    if not row:
        return None
    item = dict(row); item["metadata"] = _loads(item.pop("metadata_json", None), {}); return item


def list_preview_environments(release_id: str) -> List[Dict[str, Any]]:
    init_database()
    with get_db() as conn:
        rows = conn.execute("SELECT id FROM improvement_preview_environments WHERE release_id=? ORDER BY created_at DESC", (release_id,)).fetchall()
    return [item for row in rows if (item := get_preview_environment(row[0]))]


def update_preview_environment(preview_id: str, *, status: str, preview_url: str | None = None, metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
    current = get_preview_environment(preview_id)
    if not current:
        raise KeyError(preview_id)
    metadata_json = json.dumps(metadata, ensure_ascii=False, default=str) if metadata is not None else None
    with get_db() as conn:
        conn.execute(
            """UPDATE improvement_preview_environments SET
                 status=?, updated_at=?,
                 preview_url=CASE WHEN ? IS NOT NULL THEN ? ELSE preview_url END,
                 metadata_json=CASE WHEN ? IS NOT NULL THEN ? ELSE metadata_json END
               WHERE id=?""",
            (status, _now(), preview_url, preview_url, metadata_json, metadata_json, preview_id),
        )
        conn.commit()
    return get_preview_environment(preview_id) or current


def release_evidence(release_id: str) -> Dict[str, Any]:
    release = get_release_candidate(release_id)
    if not release: raise KeyError(release_id)
    return {"release": release, "checks": list_release_checks(release_id), "artifacts": list_release_artifacts(release_id),
            "previews": list_preview_environments(release_id)}
