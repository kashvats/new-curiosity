"""Bounded repository graph and relevance ranking for v1.1.

This stays deterministic and local: no embeddings or LLM call is needed to select
code context.  It complements (rather than replaces) the existing vector/document
search system.
"""
from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from pathlib import Path
import re
import time
import posixpath
from typing import Any, Dict, Iterable, List

from app.config import settings

_EXCLUDED = {".git", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "venv", ".venv", "dist", "build", ".next", "coverage"}
_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs"}
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_STOP = {"the", "and", "for", "with", "from", "this", "that", "into", "when", "then", "make", "add", "change", "update", "issue", "code", "file", "fix", "use", "using"}
_GRAPH_CACHE: dict[str, tuple[float, Dict[str, Any]]] = {}


@dataclass
class FileNode:
    path: str
    language: str
    symbols: List[str]
    imports: List[str]
    calls: List[str]
    line_count: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _terms(text: str) -> set[str]:
    return {m.group(0).lower() for m in _WORD_RE.finditer(text or "") if m.group(0).lower() not in _STOP}


def _iter_files(root: Path) -> Iterable[Path]:
    max_files = max(50, int(getattr(settings, "V11_REPOSITORY_GRAPH_MAX_FILES", 1200)))
    max_bytes = max(100_000, int(getattr(settings, "V11_REPOSITORY_GRAPH_MAX_BYTES", 8_000_000)))
    count = 0
    total = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _EXTENSIONS:
            continue
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if any(part in _EXCLUDED for part in rel.parts):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > 350_000 or total + size > max_bytes:
            continue
        yield path
        count += 1
        total += size
        if count >= max_files or total >= max_bytes:
            break


def _python_node(path: Path, root: Path) -> FileNode | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(text)
    except Exception:
        return None
    symbols: list[str] = []
    imports: list[str] = []
    calls: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append(node.name)
        elif isinstance(node, ast.Import):
            imports.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * int(getattr(node, "level", 0) or 0)
            if node.module:
                imports.append(prefix + node.module)
            elif prefix:
                # `from . import sibling` / `from .. import sibling`
                imports.extend(prefix + alias.name for alias in node.names)
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                calls.append(fn.id)
            elif isinstance(fn, ast.Attribute):
                calls.append(fn.attr)
    return FileNode(path.relative_to(root).as_posix(), "python", sorted(set(symbols)), sorted(set(imports)), sorted(set(calls)), text.count("\n") + 1)


def _script_node(path: Path, root: Path) -> FileNode | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    symbols = re.findall(r"(?:function|class)\s+([A-Za-z_$][\w$]*)", text)
    symbols += re.findall(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>", text)
    imports = re.findall(r"from\s+['\"]([^'\"]+)['\"]", text) + re.findall(r"require\(['\"]([^'\"]+)['\"]\)", text)
    calls = re.findall(r"\b([A-Za-z_$][\w$]*)\s*\(", text)
    return FileNode(path.relative_to(root).as_posix(), path.suffix.lower().lstrip("."), sorted(set(symbols)), sorted(set(imports)), sorted(set(calls))[:300], text.count("\n") + 1)


def _module_aliases(rel_path: str) -> set[str]:
    p = Path(rel_path)
    without = p.with_suffix("")
    parts = list(without.parts)
    aliases = {".".join(parts), without.name, without.as_posix()}
    if parts and parts[-1] == "__init__":
        aliases.add(".".join(parts[:-1]))
    if parts and parts[0] in {"src", "app"} and len(parts) > 1:
        aliases.add(".".join(parts[1:]))
    return {a for a in aliases if a}


def _import_candidates(source_path: str, raw_import: str) -> set[str]:
    """Return normalized module/path candidates for Python/JS imports.

    Python relative imports must be resolved against the source package.  Treating
    `from .b import x` as plain `b` can connect to the wrong package when multiple
    modules share the same basename.
    """
    raw = str(raw_import or "").strip()
    if not raw:
        return set()
    candidates: set[str] = set()
    if raw.startswith("."):
        # JS/TS relative path (`./foo`, `../foo`) uses slash notation.
        if raw.startswith("./") or raw.startswith("../"):
            base_dir = Path(source_path).parent.as_posix()
            normalized = posixpath.normpath(posixpath.join(base_dir, raw))
            candidates.update({normalized, normalized.replace("/", ".")})
            candidates.update({normalized + "/index", (normalized + "/index").replace("/", ".")})
            return candidates

        # Python relative import (`.b`, `..common`).  One leading dot means the
        # current package, two means its parent, etc.
        level = len(raw) - len(raw.lstrip("."))
        module = raw[level:]
        package_parts = list(Path(source_path).parent.parts)
        ascend = max(0, level - 1)
        if ascend:
            if ascend > len(package_parts):
                return set()
            package_parts = package_parts[:-ascend]
        target_parts = package_parts + ([p for p in module.split(".") if p] if module else [])
        if target_parts:
            normalized = "/".join(target_parts)
            candidates.update({normalized, ".".join(target_parts)})
        return candidates

    clean = raw.lstrip(".")
    candidates.update({clean, clean.replace("/", ".")})
    return candidates


def build_repository_graph(root: str | Path) -> Dict[str, Any]:
    base = Path(root).resolve()
    cache_key = str(base)
    ttl = max(0.0, float(getattr(settings, "V11_REPOSITORY_GRAPH_CACHE_SECONDS", 3.0)))
    cached = _GRAPH_CACHE.get(cache_key)
    if cached and ttl > 0 and (time.monotonic() - cached[0]) <= ttl:
        return cached[1]
    nodes: dict[str, FileNode] = {}
    alias_to_path: dict[str, str] = {}
    for path in _iter_files(base):
        node = _python_node(path, base) if path.suffix.lower() == ".py" else _script_node(path, base)
        if not node:
            continue
        nodes[node.path] = node
        for alias in _module_aliases(node.path):
            alias_to_path.setdefault(alias, node.path)

    edges: dict[str, list[str]] = {path: [] for path in nodes}
    reverse: dict[str, list[str]] = {path: [] for path in nodes}
    symbol_owner: dict[str, list[str]] = {}
    for path, node in nodes.items():
        for symbol in node.symbols:
            symbol_owner.setdefault(symbol.lower(), []).append(path)
        targets: set[str] = set()
        for imp in node.imports:
            candidates = _import_candidates(path, str(imp))
            for alias, target in alias_to_path.items():
                if any(
                    candidate == alias
                    or candidate.startswith(alias + ".")
                    or alias.startswith(candidate + ".")
                    or candidate.startswith(alias + "/")
                    or alias.startswith(candidate + "/")
                    for candidate in candidates if candidate
                ):
                    if target != path:
                        targets.add(target)
        edges[path] = sorted(targets)
        for target in targets:
            reverse.setdefault(target, []).append(path)
    reverse = {k: sorted(set(v)) for k, v in reverse.items()}
    result = {
        "root": str(base),
        "nodes": {path: node.to_dict() for path, node in nodes.items()},
        "edges": edges,
        "reverse_edges": reverse,
        "symbol_owner": symbol_owner,
        "file_count": len(nodes),
    }
    _GRAPH_CACHE[cache_key] = (time.monotonic(), result)
    return result


def clear_repository_graph_cache(root: str | Path | None = None) -> None:
    if root is None:
        _GRAPH_CACHE.clear()
    else:
        _GRAPH_CACHE.pop(str(Path(root).resolve()), None)


def rank_relevant_files(
    root: str | Path,
    task: str,
    *,
    seed_files: Iterable[str] = (),
    limit: int = 8,
) -> Dict[str, Any]:
    graph = build_repository_graph(root)
    nodes: Dict[str, Dict[str, Any]] = graph["nodes"]
    task_terms = _terms(task)
    normalized_seeds = {str(p).replace("\\", "/").lstrip("./") for p in seed_files if str(p)}
    scores: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}

    def add(path: str, score: float, reason: str) -> None:
        if path not in nodes:
            return
        scores[path] = scores.get(path, 0.0) + score
        reasons.setdefault(path, []).append(reason)

    for path, node in nodes.items():
        if path in normalized_seeds:
            add(path, 100.0, "explicit seed file")
        path_terms = _terms(path.replace("/", " "))
        symbol_terms = {s.lower() for s in node.get("symbols", [])}
        call_terms = {s.lower() for s in node.get("calls", [])}
        path_overlap = task_terms & path_terms
        symbol_overlap = task_terms & symbol_terms
        call_overlap = task_terms & call_terms
        if path_overlap:
            add(path, 7.0 * len(path_overlap), "task terms match path")
        if symbol_overlap:
            add(path, 12.0 * len(symbol_overlap), "task terms match symbols")
        if call_overlap:
            add(path, 2.0 * min(3, len(call_overlap)), "task terms match calls")
        if path.startswith("tests/") or "/test" in path.lower() or Path(path).name.startswith("test_"):
            if "test" in task_terms or "regression" in task_terms:
                add(path, 5.0, "test task")

    # Expand direct graph neighbors from explicit seeds and strong lexical hits.
    anchor_paths = set(normalized_seeds)
    anchor_paths.update(path for path, score in scores.items() if score >= 12.0)
    for anchor in list(anchor_paths):
        for target in graph["edges"].get(anchor, []):
            add(target, 9.0, f"imported by relevant file {anchor}")
        for source in graph["reverse_edges"].get(anchor, []):
            add(source, 7.0, f"imports relevant file {anchor}")

    # Test/source counterpart heuristic.
    for seed in list(anchor_paths):
        p = Path(seed)
        if p.name.startswith("test_"):
            stem = p.name[5:]
            for candidate in nodes:
                if Path(candidate).name == stem:
                    add(candidate, 10.0, f"source counterpart of {seed}")
        else:
            test_name = f"test_{p.name}"
            for candidate in nodes:
                if Path(candidate).name == test_name:
                    add(candidate, 8.0, f"test counterpart of {seed}")

    ranked = sorted(scores, key=lambda p: (-scores[p], p))[: max(1, min(int(limit), 24))]
    return {
        "task": task,
        "file_count_scanned": graph["file_count"],
        "selected": [
            {"path": p, "score": round(scores[p], 2), "reasons": reasons.get(p, [])[:4], "symbols": nodes[p].get("symbols", [])[:20]}
            for p in ranked
        ],
        "selected_paths": ranked,
        "graph": {
            "edges": {p: graph["edges"].get(p, [])[:20] for p in ranked},
            "reverse_edges": {p: graph["reverse_edges"].get(p, [])[:20] for p in ranked},
        },
    }


def compact_repository_context(result: Dict[str, Any], *, max_chars: int = 6000) -> str:
    lines = [f"Repository relevance scan: {result.get('file_count_scanned', 0)} files"]
    for item in result.get("selected", []):
        lines.append(
            f"- {item.get('path')} score={item.get('score')} symbols={','.join(item.get('symbols', [])[:8])} "
            f"reasons={'; '.join(item.get('reasons', [])[:2])}"
        )
    return "\n".join(lines)[:max_chars]
