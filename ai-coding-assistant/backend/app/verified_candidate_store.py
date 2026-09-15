"""Persistence and promotion of exact verified repair candidates."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict

from app.apply_changes import apply_drafted_changes, restore_project_snapshot
from app.change_timeline import create_timeline_event
from app.database import get_db, init_database
from app.project_paths import resolve_project_root
from app.verification_service import verification_service
from app.test_discovery import discover_project_checks


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def store_verified_repair(
    *, issue_id: str, project_name: str, task: str, proposed_changes: list[dict[str, Any]],
    validation: Dict[str, Any], review: Dict[str, Any], security: Dict[str, Any], quality: Dict[str, Any],
) -> Dict[str, Any]:
    init_database()
    now = _now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO verified_repairs
               (issue_id, project_name, task, proposed_changes_json, validation_json,
                review_json, security_json, quality_json, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'verified', ?)
               ON CONFLICT(issue_id) DO UPDATE SET
                 proposed_changes_json=excluded.proposed_changes_json,
                 validation_json=excluded.validation_json,
                 review_json=excluded.review_json,
                 security_json=excluded.security_json,
                 quality_json=excluded.quality_json,
                 status='verified', snapshot_id=NULL, applied_at=NULL,
                 post_apply_validation_json=NULL, rollback_reason=NULL, rolled_back_at=NULL""",
            (
                issue_id, project_name, task, json.dumps(proposed_changes), json.dumps(validation),
                json.dumps(review), json.dumps(security), json.dumps(quality), now,
            ),
        )
        conn.commit()
    return {"issue_id": issue_id, "status": "verified", "created_at": now}


def get_verified_repair(issue_id: str) -> Dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM verified_repairs WHERE issue_id = ?", (issue_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    for key in (
        "proposed_changes_json", "validation_json", "review_json", "security_json",
        "quality_json", "post_apply_validation_json",
    ):
        if key not in item:
            continue
        clean = key.removesuffix("_json")
        try:
            item[clean] = json.loads(item.pop(key) or "null")
        except Exception:
            item[clean] = None
    return item


def _post_apply_plan(candidate: Dict[str, Any]) -> list[dict[str, Any]]:
    validation = candidate.get("validation") or {}
    checks = validation.get("checks") or []
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for check in checks:
        args = check.get("args") if isinstance(check, dict) else None
        if not isinstance(args, list) or not args:
            continue
        key = tuple(str(v) for v in args)
        if key in seen:
            continue
        seen.add(key)
        output.append({"args": list(key), "cwd": check.get("cwd"), "purpose": check.get("purpose", "Post-apply verification")})
    return output


def _record_apply_state(
    issue_id: str, *, status: str, snapshot_id: str | None,
    post_validation: Dict[str, Any] | None = None,
    rollback_reason: str | None = None,
) -> None:
    applied_at = _now() if status == "applied" else None
    rolled_back_at = _now() if status == "rolled_back" else None
    with get_db() as conn:
        conn.execute(
            """UPDATE verified_repairs SET status=?, snapshot_id=?,
               applied_at=CASE WHEN ?='applied' THEN ? ELSE applied_at END,
               post_apply_validation_json=?, rollback_reason=?, rolled_back_at=? WHERE issue_id=?""",
            (
                status, snapshot_id, status, applied_at,
                json.dumps(post_validation, ensure_ascii=False, default=str) if post_validation is not None else None,
                rollback_reason, rolled_back_at, issue_id,
            ),
        )
        conn.commit()


def apply_verified_repair(issue_id: str, *, confirm: bool) -> Dict[str, Any]:
    """Apply the exact verified candidate, re-run its machine checks, rollback on failure."""
    if not confirm:
        raise ValueError("confirm must be true to apply a verified repair")
    candidate = get_verified_repair(issue_id)
    if not candidate:
        raise KeyError(issue_id)
    if candidate.get("status") != "verified":
        raise ValueError(f"Repair is not awaiting apply; current status={candidate.get('status')}")

    root = resolve_project_root(candidate["project_name"])
    results = apply_drafted_changes(candidate.get("proposed_changes") or [], root)
    snapshot_id = next((row.get("snapshot_id") for row in results if row.get("snapshot_id")), None)
    plan = _post_apply_plan(candidate)
    if not plan:
        # Backward compatibility for candidates produced before validation commands
        # were persisted: derive conservative checks from the project rather than
        # silently applying without a post-check.
        discovered = discover_project_checks(root, [c.get("path", "") for c in candidate.get("proposed_changes") or []])
        plan = [*discovered.get("quick_checks", []), *discovered.get("regression_checks", [])]

    if not plan:
        if snapshot_id:
            restore_project_snapshot(snapshot_id, root)
        reason = "No machine-verifiable post-apply checks are available"
        post_validation = {"passed": False, "status": "no_checks", "checks": [], "message": reason}
        _record_apply_state(issue_id, status="rolled_back", snapshot_id=snapshot_id, post_validation=post_validation, rollback_reason=reason)
        return {"status": "rolled_back", "issue_id": issue_id, "snapshot_id": snapshot_id, "results": results, "post_apply_validation": post_validation, "rollback_reason": reason}

    post_validation = verification_service.verify(str(root), plan)
    if not post_validation.get("passed"):
        if snapshot_id:
            restore_project_snapshot(snapshot_id, root)
        reason = "Post-apply verification failed; previous snapshot restored"
        _record_apply_state(issue_id, status="rolled_back", snapshot_id=snapshot_id, post_validation=post_validation, rollback_reason=reason)
        try:
            create_timeline_event(
                event_type="verified_repair_rolled_back",
                title=f"Rolled back repair {issue_id}", related_issue_id=issue_id,
                related_snapshot_id=snapshot_id, status="failed",
                metadata={"reason": reason, "post_apply_validation": post_validation},
            )
        except Exception:
            pass
        return {"status": "rolled_back", "issue_id": issue_id, "snapshot_id": snapshot_id, "results": results, "post_apply_validation": post_validation, "rollback_reason": reason}

    applied_at = _now()
    _record_apply_state(issue_id, status="applied", snapshot_id=snapshot_id, post_validation=post_validation)
    try:
        create_timeline_event(
            event_type="verified_repair_applied",
            title=f"Applied repair {issue_id}", related_issue_id=issue_id,
            related_snapshot_id=snapshot_id, status="success",
            metadata={"files": [r.get("path") for r in results], "post_apply_validation": post_validation},
        )
    except Exception:
        pass
    return {
        "status": "applied", "issue_id": issue_id, "snapshot_id": snapshot_id,
        "results": results, "applied_at": applied_at, "post_apply_validation": post_validation,
    }


def rollback_applied_repair(issue_id: str, *, reason: str = "Manual rollback requested") -> Dict[str, Any]:
    """Restore the snapshot created when an already-applied verified repair was promoted."""
    candidate = get_verified_repair(issue_id)
    if not candidate:
        raise KeyError(issue_id)
    if candidate.get("status") != "applied":
        raise ValueError(f"Repair is not currently applied; current status={candidate.get('status')}")
    snapshot_id = candidate.get("snapshot_id")
    if not snapshot_id:
        raise ValueError("Applied repair has no snapshot to restore")
    root = resolve_project_root(candidate["project_name"])
    restore_project_snapshot(snapshot_id, root)
    _record_apply_state(
        issue_id,
        status="rolled_back",
        snapshot_id=snapshot_id,
        post_validation=candidate.get("post_apply_validation"),
        rollback_reason=reason,
    )
    try:
        create_timeline_event(
            event_type="verified_repair_rolled_back",
            title=f"Rolled back repair {issue_id}",
            related_issue_id=issue_id,
            related_snapshot_id=snapshot_id,
            status="success",
            metadata={"reason": reason, "manual_or_controller": True},
        )
    except Exception:
        pass
    return {
        "status": "rolled_back",
        "issue_id": issue_id,
        "snapshot_id": snapshot_id,
        "rollback_reason": reason,
        "rolled_back_at": _now(),
    }


def discard_verified_repair(issue_id: str, *, reason: str = "Verified repair discarded") -> Dict[str, Any]:
    """Revoke an unapplied verified repair so no apply surface can promote it later."""
    candidate = get_verified_repair(issue_id)
    if not candidate:
        raise KeyError(issue_id)
    if candidate.get("status") == "discarded":
        return {"status": "discarded", "issue_id": issue_id, "reason": candidate.get("rollback_reason") or reason}
    if candidate.get("status") != "verified":
        raise ValueError(f"Only unapplied verified repairs can be discarded; current status={candidate.get('status')}")
    now = _now()
    with get_db() as conn:
        conn.execute(
            "UPDATE verified_repairs SET status='discarded', rollback_reason=?, rolled_back_at=? WHERE issue_id=?",
            (reason, now, issue_id),
        )
        conn.commit()
    return {"status": "discarded", "issue_id": issue_id, "reason": reason, "discarded_at": now}
