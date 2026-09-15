"""Backups and controlled promotion of drafted changes.

This module restores the public contracts used by the existing orchestrator and job
handlers while delegating path/change safety to patch_engine.
"""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from app.config import settings
from app.patch_engine import apply_changes, preview_changes


BACKUP_IGNORES = shutil.ignore_patterns(
    ".git", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "venv", ".venv", "dist", "build", ".next"
)


def create_project_snapshot(label: str = "snapshot", project_root: str | Path | None = None) -> Dict[str, Any]:
    source = Path(project_root or settings.WORKSPACE_ROOT).expanduser().resolve()
    if not source.is_dir():
        raise ValueError(f"Cannot snapshot missing project: {source}")
    snapshot_id = str(uuid.uuid4())
    backup_base = Path(settings.BACKUP_DIR).expanduser().resolve()
    target = backup_base / snapshot_id / "project"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, ignore=BACKUP_IGNORES)
    meta = {
        "snapshot_id": snapshot_id,
        "label": label,
        "source": str(source),
        "path": str(target),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (target.parent / "snapshot.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def restore_project_snapshot(snapshot_id: str, project_root: str | Path | None = None) -> Dict[str, Any]:
    destination = Path(project_root or settings.WORKSPACE_ROOT).expanduser().resolve()
    snapshot = Path(settings.BACKUP_DIR).expanduser().resolve() / snapshot_id / "project"
    if not snapshot.is_dir():
        raise ValueError(f"Snapshot not found: {snapshot_id}")
    # Restore file content from a known-good snapshot. Caller is expected to invoke this
    # only after an approval/rollback decision.
    temp_old = destination.parent / f".{destination.name}.rollback-{uuid.uuid4().hex[:8]}"
    destination.rename(temp_old)
    try:
        shutil.copytree(snapshot, destination)
        shutil.rmtree(temp_old, ignore_errors=True)
    except Exception:
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        temp_old.rename(destination)
        raise
    return {"status": "success", "snapshot_id": snapshot_id, "project_root": str(destination)}


def apply_drafted_changes(
    proposed_changes: Iterable[Dict[str, Any]],
    project_root: str | Path | None = None,
    *, create_snapshot: bool = True,
) -> List[Dict[str, Any]]:
    root = Path(project_root or settings.WORKSPACE_ROOT).expanduser().resolve()
    snapshot = create_project_snapshot("before-agent-apply", root) if create_snapshot else None
    try:
        results = apply_changes(root, proposed_changes)
        output = [r.to_dict() for r in results]
        for row in output:
            if snapshot:
                row["snapshot_id"] = snapshot["snapshot_id"]
        return output
    except Exception:
        if snapshot:
            restore_project_snapshot(snapshot["snapshot_id"], root)
        raise


def preview_drafted_changes(proposed_changes: Iterable[Dict[str, Any]], project_root: str | Path | None = None) -> List[Dict[str, Any]]:
    root = Path(project_root or settings.WORKSPACE_ROOT).expanduser().resolve()
    return [r.to_dict() for r in preview_changes(root, proposed_changes)]
