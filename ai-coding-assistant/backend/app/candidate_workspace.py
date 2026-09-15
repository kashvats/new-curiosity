"""Isolated candidate workspaces used by coding and repair agents."""
from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_IGNORES = {
    ".git", ".idea", ".vscode", "node_modules", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "venv", ".venv", "dist", "build", ".next",
}


@dataclass
class CandidateWorkspace:
    source_root: Path
    root: Path
    cleanup_on_close: bool = True

    @classmethod
    def create(cls, source_root: str | Path, *, ignore: Iterable[str] | None = None) -> "CandidateWorkspace":
        source = Path(source_root).resolve()
        if not source.is_dir():
            raise ValueError(f"Project root does not exist or is not a directory: {source}")

        temp_root = Path(tempfile.mkdtemp(prefix="ai-candidate-"))
        destination = temp_root / "project"
        ignored = set(DEFAULT_IGNORES)
        if ignore:
            ignored.update(ignore)
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns(*sorted(ignored)))
        return cls(source_root=source, root=destination)

    def close(self) -> None:
        if self.cleanup_on_close:
            shutil.rmtree(self.root.parent, ignore_errors=True)

    def __enter__(self) -> "CandidateWorkspace":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
