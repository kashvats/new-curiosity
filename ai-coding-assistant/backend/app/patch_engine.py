"""Safe file-change validation, preview, and application.

The first implementation accepts create/modify changes carrying complete candidate
content. For modifications, an optional expected_sha256 prevents stale writes.
A unified diff preview is always generated for humans and reviewers.
"""
from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List

from app.config import settings


class PatchError(ValueError):
    pass


@dataclass
class ChangeResult:
    path: str
    action: str
    status: str
    message: str = ""
    diff: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve_project_path(project_root: str | Path, relative_path: str) -> Path:
    root = Path(project_root).resolve()
    if not relative_path or Path(relative_path).is_absolute():
        raise PatchError("Change path must be a non-empty relative path")
    target = (root / relative_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise PatchError(f"Path escapes project root: {relative_path}") from exc
    return target


def validate_changes(changes: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    total_bytes = 0
    max_files = int(getattr(settings, "MAX_PATCH_FILES", 12))
    max_bytes = int(getattr(settings, "MAX_PATCH_BYTES", 500_000))

    for change in changes:
        if not isinstance(change, dict):
            raise PatchError("Every proposed change must be an object")
        action = str(change.get("action", "")).lower().strip()
        path = str(change.get("path", "")).replace("\\", "/").strip()
        if action not in {"create", "modify"}:
            raise PatchError(f"Unsupported action '{action}' for {path}; first slice allows create/modify only")
        if not path or path.startswith("/") or ".." in Path(path).parts:
            raise PatchError(f"Unsafe path: {path}")
        configured_protected = getattr(settings, "AGENT_PROTECTED_PATHS", "")
        protected = configured_protected if isinstance(configured_protected, (list, tuple, set)) else [v.strip() for v in str(configured_protected).split(",") if v.strip()]
        normalized_path = path.lstrip("./")
        for rule in protected:
            normalized_rule = str(rule).replace("\\", "/").lstrip("./")
            if normalized_rule.endswith("/") and normalized_path.startswith(normalized_rule):
                raise PatchError(f"Protected path cannot be modified by agents: {path}")
            if normalized_path == normalized_rule:
                raise PatchError(f"Protected path cannot be modified by agents: {path}")
        content = change.get("content")
        if not isinstance(content, str):
            raise PatchError(f"Missing string content for {path}")
        total_bytes += len(content.encode("utf-8"))
        normalized.append({
            "action": action,
            "path": path,
            "content": content,
            "reason": str(change.get("reason", "")),
            "expected_sha256": change.get("expected_sha256"),
        })

    if len(normalized) > max_files:
        raise PatchError(f"Too many changed files: {len(normalized)} > {max_files}")
    if total_bytes > max_bytes:
        raise PatchError(f"Patch payload too large: {total_bytes} bytes > {max_bytes}")
    return normalized


def preview_changes(project_root: str | Path, changes: Iterable[Dict[str, Any]]) -> List[ChangeResult]:
    results: List[ChangeResult] = []
    for change in validate_changes(changes):
        target = resolve_project_path(project_root, change["path"])
        old = target.read_text(encoding="utf-8") if target.exists() and target.is_file() else ""
        diff = "".join(difflib.unified_diff(
            old.splitlines(keepends=True),
            change["content"].splitlines(keepends=True),
            fromfile=f"a/{change['path']}",
            tofile=f"b/{change['path']}",
        ))
        results.append(ChangeResult(change["path"], change["action"], "preview", diff=diff))
    return results


def apply_changes(project_root: str | Path, changes: Iterable[Dict[str, Any]]) -> List[ChangeResult]:
    results: List[ChangeResult] = []
    for change in validate_changes(changes):
        target = resolve_project_path(project_root, change["path"])
        exists = target.exists()
        if change["action"] == "create" and exists:
            raise PatchError(f"Create refused because file already exists: {change['path']}")
        if change["action"] == "modify" and not exists:
            raise PatchError(f"Modify refused because file does not exist: {change['path']}")
        old = target.read_text(encoding="utf-8") if exists else ""
        expected = change.get("expected_sha256")
        if expected and _sha256_text(old) != expected:
            raise PatchError(f"Stale content detected for {change['path']}")
        target.parent.mkdir(parents=True, exist_ok=True)
        diff = "".join(difflib.unified_diff(
            old.splitlines(keepends=True),
            change["content"].splitlines(keepends=True),
            fromfile=f"a/{change['path']}",
            tofile=f"b/{change['path']}",
        ))
        target.write_text(change["content"], encoding="utf-8")
        results.append(ChangeResult(change["path"], change["action"], "success", diff=diff))
    return results
