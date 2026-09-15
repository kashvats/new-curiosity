"""Project-aware context assembly shared by IDE modes and agents.

This module intentionally stays deterministic. It gathers only bounded local evidence;
the LLM decides what it means later.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, Iterable

from app.coder import collect_code_context
from app.project_paths import resolve_project_root
from app.safe_commands import run_safe_command
from app.test_discovery import discover_project_checks
from app.config import settings
from app.repository_intelligence import rank_relevant_files, compact_repository_context


def _local_python_neighbors(root: Path, rel_path: str) -> list[str]:
    path = (root / rel_path).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return []
    if path.suffix != ".py" or not path.is_file():
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    module_names: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            module_names.update((0, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            level = int(getattr(node, "level", 0) or 0)
            if node.module:
                module_names.add((level, node.module))
            elif level:
                module_names.update((level, alias.name) for alias in node.names)
    candidates: set[str] = set()
    for level, module in module_names:
        module_parts = [part for part in module.split(".") if part]
        if level:
            package = list(path.parent.relative_to(root).parts)
            ascend = max(0, level - 1)
            if ascend > len(package):
                continue
            if ascend:
                package = package[:-ascend]
            module_path = Path(*(package + module_parts))
        else:
            module_path = Path(*module_parts)
        for candidate in (root / f"{module_path}.py", root / module_path / "__init__.py"):
            if candidate.is_file():
                candidates.add(candidate.relative_to(root).as_posix())
    tests_dir = root / "tests"
    if tests_dir.is_dir():
        test_candidate = tests_dir / f"test_{path.stem}.py"
        if test_candidate.is_file():
            candidates.add(test_candidate.relative_to(root).as_posix())
    return sorted(candidates)


def _git_context(root: Path, current_file: str | None) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    try:
        status = run_safe_command(root, ["git", "status", "--short"])
        result["status"] = status.stdout[-12000:]
    except Exception as exc:
        result["status_error"] = str(exc)
    try:
        args = ["git", "diff", "--"]
        if current_file:
            args.append(current_file.replace("\\", "/"))
        diff = run_safe_command(root, args)
        result["diff"] = diff.stdout[-20000:]
    except Exception as exc:
        result["diff_error"] = str(exc)
    return result


def build_ide_context(
    *,
    project_name: str,
    files: Iterable[str] = (),
    current_file: str | None = None,
    selected_text: str = "",
    diagnostics: Iterable[Dict[str, Any]] = (),
    terminal_output: str = "",
    project_root: str | Path | None = None,
    task: str = "",
) -> Dict[str, Any]:
    root = Path(project_root).resolve() if project_root else resolve_project_root(project_name)
    requested: list[str] = []
    for value in [current_file, *list(files)]:
        if value and value not in requested:
            requested.append(str(value).replace("\\", "/"))

    related: list[str] = []
    for rel in requested[:4]:
        related.extend(_local_python_neighbors(root, rel))
    for rel in related:
        if rel not in requested:
            requested.append(rel)

    repository_context: Dict[str, Any] = {}
    if getattr(settings, "V11_REPOSITORY_CONTEXT_ENABLED", True) and task:
        try:
            repository_context = rank_relevant_files(
                root, task, seed_files=requested,
                limit=min(int(getattr(settings, "V11_REPOSITORY_CONTEXT_MAX_FILES", 8)), int(settings.MAX_CODE_CONTEXT_FILES)),
            )
            for rel in repository_context.get("selected_paths", []):
                if rel not in requested and len(requested) < int(settings.MAX_CODE_CONTEXT_FILES):
                    requested.append(rel)
        except Exception:
            repository_context = {}

    context_files = collect_code_context(requested, project_name, str(root))
    checks = discover_project_checks(root, requested)
    return {
        "project_name": project_name,
        "project_root": str(root),
        "files": context_files,
        "requested_files": requested,
        "current_file": current_file,
        "selected_text": (selected_text or "")[:12000],
        "diagnostics": list(diagnostics)[:100],
        "terminal_output": (terminal_output or "")[-16000:],
        "git": _git_context(root, current_file),
        "test_discovery": checks,
        "repository_intelligence": repository_context,
    }


def render_context_for_llm(context: Dict[str, Any], *, max_chars: int = 50000) -> str:
    parts: list[str] = []
    for item in context.get("files", []):
        parts.append(f"--- FILE {item.get('path')} sha256={item.get('sha256', '')} ---\n{item.get('content', '')}")
    selected = context.get("selected_text")
    if selected:
        parts.append(f"--- SELECTED TEXT ---\n{selected}")
    diagnostics = context.get("diagnostics") or []
    if diagnostics:
        parts.append(f"--- EDITOR DIAGNOSTICS ---\n{diagnostics}")
    terminal = context.get("terminal_output")
    if terminal:
        parts.append(f"--- TERMINAL OUTPUT ---\n{terminal}")
    git = context.get("git") or {}
    if git.get("diff"):
        parts.append(f"--- GIT DIFF ---\n{git['diff']}")
    repo = context.get("repository_intelligence") or {}
    if repo:
        parts.append(f"--- REPOSITORY RELEVANCE ---\n{compact_repository_context(repo)}")
    checks = context.get("test_discovery") or {}
    parts.append(f"--- DISCOVERED CHECKS ---\n{checks}")
    return "\n\n".join(parts)[:max_chars]
