"""Deterministic project test/check discovery for IDE and repair modes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable


def _python_checks(root: Path, changed_files: Iterable[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    quick: list[dict[str, Any]] = [
        {"args": ["python", "-m", "compileall", "-q", "."], "purpose": "Python syntax compilation"}
    ]
    regression: list[dict[str, Any]] = []
    tests_dir = root / "tests"
    has_pytest = tests_dir.is_dir() or (root / "pytest.ini").exists() or (root / "pyproject.toml").exists()
    if has_pytest:
        targeted: list[str] = []
        for rel in changed_files:
            p = Path(rel)
            if p.suffix != ".py" or p.name.startswith("test_"):
                continue
            candidates = [
                tests_dir / f"test_{p.stem}.py",
                p.parent / f"test_{p.name}",
            ]
            for candidate in candidates:
                if candidate.exists():
                    targeted.append(candidate.relative_to(root).as_posix())
        if targeted:
            quick.append({"args": ["python", "-m", "pytest", "-q", *sorted(set(targeted))], "purpose": "Targeted pytest checks"})
        regression.append({"args": ["python", "-m", "pytest", "-q"], "purpose": "Python regression test suite"})
    if (root / "ruff.toml").exists() or (root / ".ruff.toml").exists():
        regression.append({"args": ["ruff", "check", "."], "purpose": "Ruff static analysis"})
    return quick, regression


def _node_checks(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    quick: list[dict[str, Any]] = []
    regression: list[dict[str, Any]] = []
    package_path = root / "package.json"
    if not package_path.exists():
        return quick, regression
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except Exception:
        return quick, regression
    scripts = package.get("scripts") if isinstance(package, dict) else {}
    scripts = scripts if isinstance(scripts, dict) else {}
    if "typecheck" in scripts:
        quick.append({"args": ["npm", "run", "typecheck"], "purpose": "TypeScript type check"})
    elif "check" in scripts:
        quick.append({"args": ["npm", "run", "check"], "purpose": "Project static check"})
    if "test" in scripts:
        regression.append({"args": ["npm", "test"], "purpose": "Node test suite"})
    if "lint" in scripts:
        regression.append({"args": ["npm", "run", "lint"], "purpose": "Node lint suite"})
    return quick, regression


def discover_project_checks(project_root: str | Path, changed_files: Iterable[str] = ()) -> Dict[str, Any]:
    root = Path(project_root).resolve()
    changed = [str(v).replace("\\", "/") for v in changed_files]
    quick: list[dict[str, Any]] = []
    regression: list[dict[str, Any]] = []

    is_python = any((root / name).exists() for name in ("pyproject.toml", "requirements.txt", "setup.py", "pytest.ini")) or any(root.glob("*.py"))
    if is_python:
        q, r = _python_checks(root, changed)
        quick.extend(q)
        regression.extend(r)
    if (root / "package.json").exists():
        q, r = _node_checks(root)
        quick.extend(q)
        regression.extend(r)

    # Preserve order while removing duplicate arg vectors.
    def dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[tuple[str, ...]] = set()
        out = []
        for item in items:
            key = tuple(item.get("args") or [])
            if key and key not in seen:
                seen.add(key)
                out.append(item)
        return out

    return {
        "project_root": str(root),
        "quick_checks": dedupe(quick),
        "regression_checks": dedupe(regression),
        "has_machine_checks": bool(quick or regression),
    }
