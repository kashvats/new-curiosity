"""Project API/architecture baseline capture and deterministic drift detection."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from app.config import settings
from app.database import get_db, init_database
from app.project_paths import resolve_project_root

_IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", ".venv", "venv", "dist", "build", ".next"}
_ROUTE_RE = re.compile(r"@\s*(?:[A-Za-z_][\w]*\.)?(get|post|put|patch|delete|options|head)\s*\(\s*[rubfRUBF]*[\"']([^\"']+)[\"']")
_SOURCE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".rb", ".php", ".cs"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iter_files(root: Path) -> Iterable[Path]:
    limit = max(1, int(settings.IMPROVEMENT_SOURCE_SCAN_FILES))
    count = 0
    for path in sorted(root.rglob("*")):
        if count >= limit:
            break
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in _IGNORED_DIRS for part in rel.parts) or path.suffix.lower() not in _SOURCE_EXT:
            continue
        count += 1
        yield path


def capture_project_signature_at_root(root: str | Path, *, project_name: str = "default") -> Dict[str, Any]:
    """Capture the same deterministic signature for an arbitrary isolated workspace."""
    root = Path(root).resolve()
    routes: set[str] = set()
    files: list[str] = []
    top_dirs: dict[str, int] = {}
    scanned_bytes = 0
    max_bytes = max(1, int(settings.IMPROVEMENT_SOURCE_SCAN_BYTES))

    for path in _iter_files(root):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if scanned_bytes + size > max_bytes:
            break
        scanned_bytes += size
        rel = path.relative_to(root).as_posix()
        files.append(rel)
        first = rel.split("/", 1)[0] if "/" in rel else "."
        top_dirs[first] = top_dirs.get(first, 0) + 1
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for method, route in _ROUTE_RE.findall(text):
            routes.add(f"{method.upper()} {route}")

    api_routes = sorted(routes)
    source_files = sorted(files)
    api_hash = hashlib.sha256(json.dumps(api_routes, separators=(",", ":")).encode()).hexdigest()
    architecture_payload = {"files": source_files, "top_dirs": dict(sorted(top_dirs.items()))}
    architecture_hash = hashlib.sha256(json.dumps(architecture_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "project_name": project_name,
        "api_routes": api_routes,
        "source_files": source_files,
        "top_dirs": dict(sorted(top_dirs.items())),
        "api_hash": api_hash,
        "architecture_hash": architecture_hash,
        "metadata": {"scanned_bytes": scanned_bytes, "source_file_count": len(source_files), "api_route_count": len(api_routes)},
    }


def capture_project_signature(project_name: str = "default") -> Dict[str, Any]:
    return capture_project_signature_at_root(resolve_project_root(project_name), project_name=project_name)


def compare_project_signatures(current: Dict[str, Any], baseline: Dict[str, Any]) -> Dict[str, Any]:
    current_routes = set(current.get("api_routes") or [])
    baseline_routes = set(baseline.get("api_routes") or [])
    current_files = set(current.get("source_files") or [])
    baseline_files = set(baseline.get("source_files") or [])

    removed_routes = sorted(baseline_routes - current_routes)
    added_routes = sorted(current_routes - baseline_routes)
    removed_files = sorted(baseline_files - current_files)
    added_files = sorted(current_files - baseline_files)

    union = current_files | baseline_files
    similarity = 1.0 if not union else len(current_files & baseline_files) / len(union)
    score = 100.0
    score -= min(60.0, len(removed_routes) * 15.0)
    score -= min(20.0, len(added_routes) * 2.0)
    score -= min(20.0, len(removed_files) * 2.0)
    if similarity < 0.7:
        score -= min(20.0, (0.7 - similarity) * 50.0)
    score = max(0.0, min(100.0, round(score, 2)))

    findings: list[Dict[str, Any]] = []
    if removed_routes:
        findings.append({
            "category": "drift", "severity": "high", "code": "api_contract_removed",
            "message": f"{len(removed_routes)} API route(s) present in the approved baseline are missing.",
            "evidence": {"removed_routes": removed_routes[:50]}, "likely_files": [],
            "suggested_task": "Review the removed API routes against the approved contract baseline and either restore compatibility or explicitly approve a new baseline.",
            "risk": "high", "benefit": 0.9, "confidence": 0.99, "urgency": 0.9, "estimated_cost": 1.2,
            "validation_plan": [], "actionable": False,
        })
    if added_routes:
        findings.append({
            "category": "drift", "severity": "low", "code": "api_contract_added",
            "message": f"{len(added_routes)} API route(s) were added since the approved baseline.",
            "evidence": {"added_routes": added_routes[:50]}, "likely_files": [],
            "suggested_task": "Review newly added API routes and approve a refreshed baseline if they are intentional.",
            "risk": "low", "benefit": 0.3, "confidence": 0.99, "urgency": 0.3, "estimated_cost": 0.4,
            "validation_plan": [], "actionable": False,
        })
    if removed_files or similarity < 0.7:
        findings.append({
            "category": "drift", "severity": "medium", "code": "architecture_layout_drift",
            "message": "Repository source layout materially differs from the approved architecture baseline.",
            "evidence": {"removed_files": removed_files[:50], "added_files": added_files[:50], "file_similarity": round(similarity, 4)},
            "likely_files": [],
            "suggested_task": "Review architecture-layout drift and approve a refreshed baseline if the structural change is intentional.",
            "risk": "medium", "benefit": 0.45, "confidence": 0.9, "urgency": 0.45, "estimated_cost": 0.5,
            "validation_plan": [], "actionable": False,
        })

    return {
        "score": score,
        "changed": bool(removed_routes or added_routes or removed_files or added_files),
        "api": {"removed": removed_routes, "added": added_routes},
        "architecture": {"removed_files": removed_files, "added_files": added_files, "file_similarity": round(similarity, 4)},
        "hashes": {
            "current_api": current.get("api_hash"), "baseline_api": baseline.get("api_hash"),
            "current_architecture": current.get("architecture_hash"), "baseline_architecture": baseline.get("architecture_hash"),
        },
        "findings": findings,
    }


def create_project_baseline(project_name: str, *, label: str = "approved", activate: bool = True) -> Dict[str, Any]:
    init_database()
    payload = capture_project_signature(project_name)
    baseline_id = str(uuid.uuid4())
    now = _now()
    with get_db() as conn:
        if activate:
            conn.execute("UPDATE project_baselines SET active = 0 WHERE project_name = ?", (project_name,))
        conn.execute(
            """INSERT INTO project_baselines (id, project_name, label, payload_json, active, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (baseline_id, project_name, label, json.dumps(payload, ensure_ascii=False), 1 if activate else 0, now),
        )
        conn.commit()
    return get_project_baseline(baseline_id) or {"id": baseline_id, "project_name": project_name, "payload": payload}


def _row_to_baseline(row: Any) -> Dict[str, Any]:
    item = dict(row)
    try:
        item["payload"] = json.loads(item.pop("payload_json"))
    except Exception:
        item["payload"] = {}
    item["active"] = bool(item.get("active"))
    return item


def get_project_baseline(baseline_id: str) -> Dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM project_baselines WHERE id = ?", (baseline_id,)).fetchone()
    return _row_to_baseline(row) if row else None


def active_project_baseline(project_name: str) -> Dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM project_baselines WHERE project_name = ? AND active = 1 ORDER BY created_at DESC LIMIT 1",
            (project_name,),
        ).fetchone()
    return _row_to_baseline(row) if row else None


def list_project_baselines(project_name: str, *, limit: int = 50) -> List[Dict[str, Any]]:
    init_database()
    limit = max(1, min(int(limit), 200))
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM project_baselines WHERE project_name = ? ORDER BY created_at DESC LIMIT ?",
            (project_name, limit),
        ).fetchall()
    return [_row_to_baseline(row) for row in rows]


def project_drift(project_name: str) -> Dict[str, Any]:
    current = capture_project_signature(project_name)
    baseline = active_project_baseline(project_name)
    if not baseline:
        return {
            "project_name": project_name, "baseline": None, "current": current,
            "score": 100.0, "changed": False, "findings": [], "status": "no_baseline",
        }
    comparison = compare_project_signatures(current, baseline.get("payload") or {})
    return {"project_name": project_name, "baseline": baseline, "current": current, "status": "compared", **comparison}
