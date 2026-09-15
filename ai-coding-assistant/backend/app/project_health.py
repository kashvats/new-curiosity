"""Deterministic, bounded project-health snapshots for manual improvement cycles.

The health layer intentionally avoids LLM judgment. It converts observable project
facts and machine checks into normalized dimensions plus actionable findings. This
makes before/after comparisons reproducible and safe to use as controller evidence.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List

from app.config import settings
from app.dependency_health import analyze_dependency_health
from app.project_baselines import project_drift
from app.project_paths import resolve_project_root
from app.security_review import review_security
from app.test_discovery import discover_project_checks
from app.verification_service import verification_service

_IGNORED_DIRS = {
    ".git", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".venv", "venv", "dist", "build", ".next", "coverage",
}
_SOURCE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".rb",
    ".php", ".cs", ".c", ".h", ".cpp", ".hpp", ".yml", ".yaml", ".toml",
}


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, round(float(value), 2)))


def _dedupe_checks(items: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
    seen: set[tuple[str, ...]] = set()
    output: list[Dict[str, Any]] = []
    for item in items:
        args = item.get("args") if isinstance(item, dict) else None
        if not isinstance(args, list) or not args:
            continue
        key = tuple(str(v) for v in args)
        if key in seen:
            continue
        seen.add(key)
        output.append(dict(item))
    return output


def _iter_source_files(root: Path) -> Iterable[Path]:
    max_files = max(1, int(settings.IMPROVEMENT_SOURCE_SCAN_FILES))
    yielded = 0
    for path in sorted(root.rglob("*")):
        if yielded >= max_files:
            break
        if not path.is_file() or any(part in _IGNORED_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix.lower() not in _SOURCE_EXTENSIONS:
            continue
        yielded += 1
        yield path


def _scan_source(root: Path) -> Dict[str, Any]:
    max_bytes = max(1, int(settings.IMPROVEMENT_SOURCE_SCAN_BYTES))
    total_bytes = 0
    changes: list[Dict[str, Any]] = []
    todo_count = 0
    large_files: list[Dict[str, Any]] = []
    source_files = 0
    language_counts: dict[str, int] = {}

    for path in _iter_source_files(root):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if total_bytes + size > max_bytes:
            break
        total_bytes += size
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = path.relative_to(root).as_posix()
        source_files += 1
        language_counts[path.suffix.lower() or "other"] = language_counts.get(path.suffix.lower() or "other", 0) + 1
        upper = text.upper()
        todo_count += upper.count("TODO") + upper.count("FIXME")
        line_count = text.count("\n") + 1
        if line_count >= 800:
            large_files.append({"path": rel, "lines": line_count})
        # The generated-change security gate is useful for production source but
        # intentionally adversarial test fixtures often contain unsafe examples.
        # Exclude conventional test paths from repository health security scoring.
        if not (
            rel.startswith("tests/") or rel.startswith("test/") or
            Path(rel).name.startswith("test_") or Path(rel).name.endswith("_test.py")
        ):
            changes.append({"path": rel, "content": text})

    security = review_security(changes)
    # Health output must never echo source contents or suspected secret values.
    return {
        "source_files": source_files,
        "scanned_bytes": total_bytes,
        "language_counts": language_counts,
        "todo_count": todo_count,
        "large_files": large_files[:20],
        "security": security,
    }


def _test_dimension(root: Path, changed_files: Iterable[str], run_checks: bool) -> tuple[float, Dict[str, Any], list[Dict[str, Any]]]:
    discovered = discover_project_checks(root, changed_files)
    plan = _dedupe_checks([*discovered.get("quick_checks", []), *discovered.get("regression_checks", [])])
    findings: list[Dict[str, Any]] = []

    if not plan:
        findings.append({
            "category": "tests", "severity": "medium", "code": "no_machine_checks",
            "message": "No machine-verifiable test, lint, type-check, or compile checks were discovered.",
            "likely_files": [],
            "suggested_task": "Add a minimal automated verification suite for the project's critical behavior without changing public APIs.",
            "risk": "medium", "benefit": 0.75, "confidence": 0.9, "urgency": 0.75, "estimated_cost": 1.6,
            "validation_plan": [],
        })
        return 45.0, {"status": "no_checks", "passed": False, "checks": [], "discovered": discovered}, findings

    if not run_checks:
        has_regression = bool(discovered.get("regression_checks"))
        score = 80.0 if has_regression else 68.0
        return score, {"status": "not_run", "passed": None, "checks": [], "plan": plan, "discovered": discovered}, findings

    result = verification_service.verify(str(root), plan)
    checks = result.get("checks", [])
    passed_count = sum(1 for check in checks if check.get("passed"))
    ratio = passed_count / max(1, len(checks))
    score = 20.0 + 80.0 * ratio
    if not result.get("passed"):
        failed = [
            {
                "args": check.get("args", []),
                "status": check.get("status"),
                "returncode": check.get("returncode"),
                "stderr": str(check.get("stderr") or check.get("message") or "")[-6000:],
                "stdout": str(check.get("stdout") or "")[-3000:],
                "purpose": check.get("purpose", ""),
            }
            for check in checks if not check.get("passed")
        ]
        findings.append({
            "category": "tests", "severity": "high", "code": "machine_checks_failing",
            "message": f"{len(failed)} discovered machine check(s) are failing.",
            "evidence": {"failed_checks": failed},
            "likely_files": [],
            "suggested_task": "Fix the currently failing machine checks with the smallest root-cause change, preserving existing behavior outside the failure.",
            "risk": "medium", "benefit": 1.0, "confidence": 0.98, "urgency": 1.0, "estimated_cost": 1.0,
            "validation_plan": plan,
        })
    return _clamp(score), {**result, "plan": plan, "discovered": discovered}, findings


def capture_project_health(
    project_name: str = "default",
    *,
    run_checks: bool = True,
    changed_files: Iterable[str] = (),
) -> Dict[str, Any]:
    """Capture a bounded health snapshot without modifying the project."""
    root = resolve_project_root(project_name)
    source = _scan_source(root)
    findings: list[Dict[str, Any]] = []

    test_score, checks, test_findings = _test_dimension(root, changed_files, run_checks)
    findings.extend(test_findings)

    dependency_health = analyze_dependency_health(root)
    findings.extend(dependency_health.get("findings", []))
    drift = project_drift(project_name)
    findings.extend(drift.get("findings", []))

    security = source["security"]
    counts = security.get("counts", {})
    security_score = _clamp(
        100
        - 35 * counts.get("critical", 0)
        - 20 * counts.get("high", 0)
        - 7 * counts.get("medium", 0)
        - 2 * counts.get("low", 0)
    )
    for finding in security.get("findings", [])[:20]:
        severity = str(finding.get("severity", "medium"))
        findings.append({
            "category": "security", "severity": severity, "code": str(finding.get("rule_id", "security_finding")),
            "message": str(finding.get("message", "Security issue detected")),
            "evidence": {"path": finding.get("path"), "rule_id": finding.get("rule_id")},
            "likely_files": [finding.get("path")] if finding.get("path") else [],
            "suggested_task": f"Remediate the {finding.get('rule_id', 'security')} finding in {finding.get('path', 'the affected source')} without weakening validation or security controls.",
            "risk": "high" if severity in {"critical", "high"} else "medium",
            "benefit": 1.0 if severity in {"critical", "high"} else 0.7,
            "confidence": 0.95, "urgency": 1.0 if severity == "critical" else 0.85, "estimated_cost": 1.2,
            "validation_plan": checks.get("plan", []),
            # Medium static patterns are useful review evidence but are too noisy to
            # auto-target. Critical/high findings remain actionable recommendations.
            "actionable": severity in {"critical", "high"},
        })

    readme = next((p for p in (root / "README.md", root / "README.rst", root / "README.txt") if p.exists()), None)
    tests_present = (root / "tests").is_dir() or (root / "test").is_dir()
    env_example = (root / ".env.example").exists()
    has_env = (root / ".env").exists()
    has_ci = (root / ".github" / "workflows").is_dir() or (root / ".gitlab-ci.yml").exists() or (root / "Jenkinsfile").exists()

    architecture_score = 100.0
    if not tests_present and source["source_files"]:
        architecture_score -= 15
    if len(source["large_files"]) > 0:
        architecture_score -= min(25, 5 * len(source["large_files"]))
        largest = source["large_files"][0]
        findings.append({
            "category": "architecture", "severity": "medium", "code": "large_module",
            "message": f"Large source module detected: {largest['path']} ({largest['lines']} lines).",
            "evidence": largest,
            "likely_files": [largest["path"]],
            "suggested_task": f"Reduce complexity in {largest['path']} with a small behavior-preserving refactor and add/retain regression coverage.",
            "risk": "medium", "benefit": 0.55, "confidence": 0.7, "urgency": 0.45, "estimated_cost": 2.0,
            "validation_plan": checks.get("plan", []),
        })
    if not has_ci:
        architecture_score -= 5

    knowledge_score = 100.0 if readme else 45.0
    if not readme:
        findings.append({
            "category": "knowledge", "severity": "low", "code": "missing_readme",
            "message": "Project README is missing.", "likely_files": ["README.md"],
            "suggested_task": "Create a concise README describing setup, run, test, and architecture basics using only facts present in the repository.",
            "risk": "low", "benefit": 0.35, "confidence": 0.95, "urgency": 0.25, "estimated_cost": 0.6,
            "validation_plan": checks.get("plan", []),
        })
    if has_env and not env_example:
        knowledge_score -= 15
        findings.append({
            "category": "knowledge", "severity": "medium", "code": "missing_env_example",
            "message": "A .env file exists but .env.example is missing.", "likely_files": [".env.example"],
            "suggested_task": "Create .env.example with variable names and safe placeholder values inferred from configuration code; do not copy secrets from .env.",
            "risk": "low", "benefit": 0.5, "confidence": 0.9, "urgency": 0.55, "estimated_cost": 0.6,
            "validation_plan": checks.get("plan", []),
        })

    quality_score = 100.0
    if source["todo_count"]:
        quality_score -= min(20, source["todo_count"] * 2)
    if source["large_files"]:
        quality_score -= min(20, len(source["large_files"]) * 4)
    if source["source_files"] and not tests_present:
        quality_score -= 15

    dimensions = {
        "tests": _clamp(test_score),
        "security": _clamp(security_score),
        "architecture": _clamp(architecture_score),
        "quality": _clamp(quality_score),
        "knowledge": _clamp(knowledge_score),
        "dependencies": _clamp(dependency_health.get("score", 100.0)),
        "drift": _clamp(drift.get("score", 100.0)),
    }
    # Part 5 adds dependency reproducibility and approved-contract drift while
    # keeping tests/security as the dominant signals.
    weights = {
        "tests": 0.30, "security": 0.23, "architecture": 0.13, "quality": 0.12,
        "knowledge": 0.08, "dependencies": 0.08, "drift": 0.06,
    }
    health_score = _clamp(sum(dimensions[name] * weight for name, weight in weights.items()))

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings.sort(key=lambda item: (severity_order.get(str(item.get("severity", "low")), 9), str(item.get("code", ""))))

    return {
        "project_name": project_name,
        "project_root": str(root),
        "health_score": health_score,
        "dimensions": dimensions,
        "findings": findings,
        "checks": checks,
        "metadata": {
            "source_files": source["source_files"],
            "scanned_bytes": source["scanned_bytes"],
            "language_counts": source["language_counts"],
            "todo_count": source["todo_count"],
            "large_files": source["large_files"],
            "readme_present": bool(readme),
            "tests_present": tests_present,
            "ci_present": has_ci,
            "env_example_present": env_example,
            "run_checks": run_checks,
            "dependency_health": dependency_health.get("metadata", {}),
            "drift_status": drift.get("status"),
            "drift": {
                "changed": drift.get("changed", False),
                "api": drift.get("api", {}),
                "architecture": drift.get("architecture", {}),
                "baseline_id": (drift.get("baseline") or {}).get("id"),
            },
        },
    }
