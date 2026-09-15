"""Bounded repository navigation for IDE clients.

No shell, embeddings, or LLM is required. These primitives keep basic IDE navigation
available even when optional AI/vector services are offline.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable

from app.codebase_indexing import build_project_symbol_index

EXCLUDED_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "venv", ".venv", "dist", "build", ".next"}
TEXT_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".c", ".cpp", ".h", ".hpp", ".json", ".yaml", ".yml", ".toml", ".md", ".txt", ".html", ".css", ".scss", ".sql", ".sh"}


def iter_project_files(root: str | Path, *, max_files: int = 5000) -> Iterable[Path]:
    base = Path(root).resolve()
    count = 0
    for path in sorted(base.rglob("*")):
        if any(part in EXCLUDED_DIRS for part in path.relative_to(base).parts):
            continue
        if not path.is_file():
            continue
        yield path
        count += 1
        if count >= max_files:
            break


def repository_tree(root: str | Path, *, max_files: int = 2000) -> Dict[str, Any]:
    base = Path(root).resolve()
    files = []
    for path in iter_project_files(base, max_files=max_files):
        rel = path.relative_to(base).as_posix()
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        files.append({"path": rel, "size": size, "extension": path.suffix.lower()})
    return {"root": str(base), "files": files, "count": len(files), "truncated": len(files) >= max_files}


def search_project_text(root: str | Path, query: str, *, max_results: int = 100, max_file_bytes: int = 300_000) -> Dict[str, Any]:
    base = Path(root).resolve()
    needle = (query or "").strip()
    if not needle:
        raise ValueError("Search query cannot be empty")
    lowered = needle.lower()
    results = []
    for path in iter_project_files(base):
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        try:
            if path.stat().st_size > max_file_bytes:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if lowered in line.lower():
                results.append({
                    "path": path.relative_to(base).as_posix(),
                    "line": line_no,
                    "preview": line.strip()[:500],
                })
                if len(results) >= max_results:
                    return {"query": needle, "results": results, "truncated": True}
    return {"query": needle, "results": results, "truncated": False}


def search_symbols(root: str | Path, query: str = "") -> Dict[str, Any]:
    index_result = build_project_symbol_index(str(Path(root).resolve()))
    query_lower = (query or "").strip().lower()
    matches = []
    for file_path, symbols in index_result.get("index", {}).items():
        for kind in ("classes", "functions"):
            for name in symbols.get(kind, []):
                if not query_lower or query_lower in name.lower():
                    matches.append({"path": file_path.replace("\\", "/"), "kind": "class" if kind == "classes" else "function", "name": name})
    return {"query": query, "matches": matches[:500], "count": min(len(matches), 500), "truncated": len(matches) > 500}
