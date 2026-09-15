"""Offline dependency-health inspection for improvement cycles.

Part 5 intentionally does not contact package registries or mutate manifests. The
scanner only evaluates repository-local dependency declarations and lockfile hygiene.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable

_PY_REQ_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*([<>=!~].*)?$")
_IGNORED_PREFIXES = ("#", "-r ", "--requirement ", "-c ", "--constraint ")


def _finding(
    *, code: str, message: str, likely_files: Iterable[str], severity: str = "medium",
    task: str, confidence: float = 0.9, benefit: float = 0.55, urgency: float = 0.5,
    cost: float = 0.8, actionable: bool = True,
) -> Dict[str, Any]:
    return {
        "category": "dependencies",
        "severity": severity,
        "code": code,
        "message": message,
        "evidence": {"files": list(likely_files)},
        "likely_files": list(likely_files),
        "suggested_task": task,
        "risk": "medium" if actionable else "low",
        "benefit": benefit,
        "confidence": confidence,
        "urgency": urgency,
        "estimated_cost": cost,
        "validation_plan": [],
        "actionable": actionable,
    }


def _python_requirements(root: Path) -> tuple[list[Dict[str, Any]], Dict[str, Any]]:
    findings: list[Dict[str, Any]] = []
    req_files = sorted(root.glob("requirements*.txt"))[:12]
    unpinned: list[tuple[str, str]] = []
    exact_versions: dict[str, set[str]] = {}
    parsed = 0

    for path in req_files:
        rel = path.relative_to(root).as_posix()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith(_IGNORED_PREFIXES) or line.startswith(("git+", "http://", "https://", "-e ")):
                continue
            line = line.split(";", 1)[0].strip()
            match = _PY_REQ_RE.match(line)
            if not match:
                continue
            parsed += 1
            name = match.group(1).lower().replace("_", "-")
            spec = (match.group(2) or "").strip()
            if not spec.startswith("==") or "," in spec or "*" in spec:
                unpinned.append((rel, line))
            if spec.startswith("==") and "," not in spec and "*" not in spec:
                exact_versions.setdefault(name, set()).add(spec[2:].strip())

    if unpinned:
        files = sorted({item[0] for item in unpinned})
        findings.append(_finding(
            code="python_unpinned_dependencies",
            message=f"{len(unpinned)} Python dependency declaration(s) are not exact-pinned.",
            likely_files=files,
            task="Make direct Python dependency versions reproducible using exact pins or the project's existing lock/constraint strategy; preserve compatibility and validate the existing test suite.",
            severity="medium", confidence=0.92, benefit=0.6, urgency=0.5, cost=1.0, actionable=False,
        ))

    conflicts = {name: sorted(versions) for name, versions in exact_versions.items() if len(versions) > 1}
    if conflicts:
        conflict_files = [p.relative_to(root).as_posix() for p in req_files]
        findings.append(_finding(
            code="python_conflicting_pins",
            message=f"Conflicting exact pins were found for {len(conflicts)} Python package(s).",
            likely_files=conflict_files,
            task="Resolve conflicting Python dependency pins using the versions required by the repository and tests; do not perform unrelated upgrades.",
            severity="high", confidence=0.98, benefit=0.8, urgency=0.8, cost=1.0,
        ))

    return findings, {
        "requirements_files": [p.relative_to(root).as_posix() for p in req_files],
        "parsed_dependencies": parsed,
        "unpinned_count": len(unpinned),
        "conflicting_pins": conflicts,
    }


def _node_dependencies(root: Path) -> tuple[list[Dict[str, Any]], Dict[str, Any]]:
    package = root / "package.json"
    if not package.exists():
        return [], {"package_json": False, "dependency_count": 0, "lockfile": None, "unbounded_count": 0}

    findings: list[Dict[str, Any]] = []
    try:
        data = json.loads(package.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return [
            _finding(
                code="invalid_package_json",
                message="package.json could not be parsed as JSON.",
                likely_files=["package.json"],
                task="Repair package.json syntax without changing dependency intent, then run the project's existing package/test checks.",
                severity="high", confidence=1.0, benefit=0.85, urgency=0.9, cost=0.5,
            )
        ], {"package_json": True, "parse_error": True, "dependency_count": 0, "lockfile": None, "unbounded_count": 0}

    deps: dict[str, str] = {}
    for key in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        value = data.get(key)
        if isinstance(value, dict):
            deps.update({str(name): str(version) for name, version in value.items()})

    unbounded = {name: spec for name, spec in deps.items() if spec.strip().lower() in {"*", "latest", "x"}}
    if unbounded:
        findings.append(_finding(
            code="node_unbounded_dependencies",
            message=f"{len(unbounded)} Node dependency declaration(s) use unbounded versions.",
            likely_files=["package.json"],
            task="Replace unbounded Node dependency versions with repository-compatible bounded versions and refresh the existing lockfile using the project's package manager.",
            severity="medium", confidence=0.98, benefit=0.65, urgency=0.55, cost=1.0, actionable=False,
        ))

    lock_candidates = ["package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb"]
    lockfile = next((name for name in lock_candidates if (root / name).exists()), None)
    if deps and not lockfile:
        findings.append(_finding(
            code="node_missing_lockfile",
            message="Node dependencies are declared but no recognized lockfile is present.",
            likely_files=["package.json"],
            task="Add the lockfile for the package manager already indicated by the repository, without changing application behavior or performing unrelated dependency upgrades.",
            severity="medium", confidence=0.88, benefit=0.55, urgency=0.45, cost=0.8, actionable=False,
        ))

    return findings, {
        "package_json": True,
        "dependency_count": len(deps),
        "lockfile": lockfile,
        "unbounded_count": len(unbounded),
    }


def analyze_dependency_health(root: Path) -> Dict[str, Any]:
    """Return an offline, deterministic dependency score and actionable evidence."""
    python_findings, python_meta = _python_requirements(root)
    node_findings, node_meta = _node_dependencies(root)
    findings = [*python_findings, *node_findings]

    penalties = {
        "python_unpinned_dependencies": 12,
        "python_conflicting_pins": 30,
        "invalid_package_json": 35,
        "node_unbounded_dependencies": 15,
        "node_missing_lockfile": 10,
    }
    score = 100.0 - sum(penalties.get(str(item.get("code")), 5) for item in findings)
    return {
        "score": max(0.0, min(100.0, round(score, 2))),
        "findings": findings,
        "metadata": {"python": python_meta, "node": node_meta, "network_used": False},
    }
