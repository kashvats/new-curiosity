"""Single source of truth for workspace/project path resolution."""
from __future__ import annotations

from pathlib import Path
from app.config import settings


def workspace_root() -> Path:
    return Path(settings.WORKSPACE_ROOT).expanduser().resolve()


def resolve_project_root(project_name: str | None = None) -> Path:
    root = workspace_root()
    name = (project_name or "default").strip()
    project = root if name in {"", ".", "default"} else (root / name).resolve()
    try:
        project.relative_to(root)
    except ValueError as exc:
        raise ValueError("Project name escapes workspace") from exc
    if not project.is_dir():
        raise ValueError(f"Project not found: {project}")
    return project
