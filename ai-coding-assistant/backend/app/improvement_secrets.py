"""Part 11 secret-provider abstraction.

Sensitive scheduler/integration settings may come from ordinary environment-backed
Pydantic settings or from Docker/Kubernetes-style files under a secrets directory.
Secret values are never returned by status helpers.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from app.config import settings

_ALLOWED = {"env", "file", "env_or_file"}


def secret_provider_name() -> str:
    raw = str(getattr(settings, "IMPROVEMENT_SECRETS_PROVIDER", "env") or "env").strip().lower()
    return raw if raw in _ALLOWED else "env"


def _file_value(name: str) -> str:
    root = Path(str(getattr(settings, "IMPROVEMENT_SECRETS_DIR", "/run/secrets") or "/run/secrets"))
    candidate = root / name
    try:
        if not candidate.is_file():
            return ""
        # Secrets should be small. Avoid accidentally reading mounted data files.
        if candidate.stat().st_size > 64 * 1024:
            raise ValueError(f"Secret file is too large: {name}")
        return candidate.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def get_secret(name: str, *, default: str = "") -> str:
    """Resolve a setting without exposing where callers store the value."""
    provider = secret_provider_name()
    env_value = str(getattr(settings, name, "") or "")
    if provider == "env":
        return env_value or default
    file_value = _file_value(name)
    if provider == "file":
        return file_value or default
    return file_value or env_value or default


def secret_provider_status() -> Dict[str, Any]:
    provider = secret_provider_name()
    root = Path(str(getattr(settings, "IMPROVEMENT_SECRETS_DIR", "/run/secrets") or "/run/secrets"))
    return {
        "provider": provider,
        "secrets_dir": str(root),
        "secrets_dir_available": root.is_dir() if provider in {"file", "env_or_file"} else None,
        "values_exposed": False,
        "automatic_source_apply_enabled": False,
    }
