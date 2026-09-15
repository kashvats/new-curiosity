"""Runtime capability registry for the agentic coding system.

The registry is intentionally deterministic: planners and agents consult facts about
this installation before attempting tools, models, or commands.
"""
from __future__ import annotations

import os
import platform
import shutil
import importlib.util
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List

from app.config import settings


@dataclass(frozen=True)
class CapabilityProfile:
    workspace_root: str
    workspace_writable: bool
    cpu_count: int
    memory_total_bytes: int | None
    docker_available: bool
    git_available: bool
    pytest_available: bool
    node_available: bool
    npm_available: bool
    ollama_configured: bool
    qdrant_configured: bool
    browser_configured: bool
    qdrant_package_available: bool
    embedding_package_available: bool
    watcher_package_available: bool
    allowed_executables: List[str]
    max_repair_attempts: int
    max_patch_files: int
    max_patch_bytes: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _memory_total_bytes() -> int | None:
    try:
        if hasattr(os, "sysconf"):
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            return int(pages * page_size)
    except (ValueError, OSError, AttributeError):
        pass
    return None


def get_capability_profile() -> CapabilityProfile:
    root = Path(settings.WORKSPACE_ROOT).expanduser()
    writable = False
    try:
        root.mkdir(parents=True, exist_ok=True)
        writable = os.access(root, os.W_OK)
    except OSError:
        writable = False

    configured = getattr(settings, "AGENT_ALLOWED_EXECUTABLES", "")
    allowed = list(configured) if isinstance(configured, (list, tuple, set)) else [v.strip() for v in str(configured).split(",") if v.strip()]
    return CapabilityProfile(
        workspace_root=str(root),
        workspace_writable=writable,
        cpu_count=os.cpu_count() or 1,
        memory_total_bytes=_memory_total_bytes(),
        docker_available=shutil.which("docker") is not None,
        git_available=shutil.which("git") is not None,
        pytest_available=shutil.which("pytest") is not None,
        node_available=shutil.which("node") is not None,
        npm_available=shutil.which("npm") is not None,
        ollama_configured=bool(settings.OLLAMA_BASE_URL),
        qdrant_configured=bool(settings.QDRANT_HOST),
        browser_configured=bool(getattr(settings, "BROWSER_ALLOWED_HOSTS", "")),
        qdrant_package_available=importlib.util.find_spec("qdrant_client") is not None,
        embedding_package_available=importlib.util.find_spec("sentence_transformers") is not None,
        watcher_package_available=importlib.util.find_spec("watchdog") is not None,
        allowed_executables=allowed,
        max_repair_attempts=int(getattr(settings, "MAX_REPAIR_ATTEMPTS", 4)),
        max_patch_files=int(getattr(settings, "MAX_PATCH_FILES", 12)),
        max_patch_bytes=int(getattr(settings, "MAX_PATCH_BYTES", 500_000)),
    )


def capability_summary() -> Dict[str, Any]:
    profile = get_capability_profile().to_dict()
    profile["platform"] = platform.platform()
    return profile
