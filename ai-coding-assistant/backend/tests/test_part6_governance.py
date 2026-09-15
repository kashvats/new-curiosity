import hashlib
import json

import pytest

from app.config import settings
from app.database import get_db, init_database


def _workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    project = workspace / "demo"
    project.mkdir(parents=True)
    monkeypatch.setattr(settings, "WORKSPACE_ROOT", str(workspace))
    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "part6.db"))
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(settings, "AGENT_ALLOWED_EXECUTABLES", "python,pytest,git,npm,ruff,mypy")
    init_database()
    return workspace, project


def _finding_snapshot(project_root, *, likely_files=None):
    return {
        "project_name": "demo", "project_root": str(project_root), "health_score": 70.0,
        "dimensions": {"tests": 80, "security": 100, "architecture": 80, "quality": 80, "knowledge": 50, "dependencies": 100, "drift": 100},
        "findings": [{
            "category": "architecture", "severity": "medium", "code": "large_module",
            "message": "Module needs cleanup.", "likely_files": likely_files or ["api.py"],
            "suggested_task": "Refactor the module without changing public API behavior.",
            "risk": "medium", "benefit": 0.8, "confidence": 0.9, "urgency": 0.8,
            "estimated_cost": 0.5, "validation_plan": [],
        }],
        "checks": {"passed": True, "checks": [], "plan": []},
        "metadata": {"source_files": 1},
    }


def test_part6_schema_adds_policy_governance_impact_and_cancel_state(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    with get_db() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        cycles = {row[1] for row in conn.execute("PRAGMA table_info(improvement_cycles)").fetchall()}
        candidates = {row[1] for row in conn.execute("PRAGMA table_info(improvement_candidates)").fetchall()}
        experiments = {row[1] for row in conn.execute("PRAGMA table_info(improvement_experiments)").fetchall()}
    assert {"improvement_policies", "improvement_governance_checks", "improvement_test_impacts"}.issubset(tables)
    assert {"policy_snapshot_json", "cancel_requested", "cancelled_at"}.issubset(cycles)
    assert {"candidate_fingerprint", "suppressed", "suppression_reason", "repeat_count", "impact_memory_json"}.issubset(candidates)
    assert "discarded_at" in experiments


def test_project_policy_is_versioned_and_cannot_disable_human_apply(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app.improvement_policy import resolved_improvement_policy, save_improvement_policy

    first = save_improvement_policy("demo", {
        "allowed_risks": ["low"],
        "approval": {"human_source_apply_required": False},
        "protected_api": {"routes": ["GET /health"]},
    })
    second = save_improvement_policy("demo", {"allowed_risks": ["low", "medium"]})
    resolved = resolved_improvement_policy("demo")
    assert first["version"] == 1
    assert second["version"] == 2
    assert resolved["version"] == 2
    assert resolved["policy"]["approval"]["human_source_apply_required"] is True


def test_governance_blocks_removal_of_approved_api_route(tmp_path, monkeypatch):
    _, project = _workspace(tmp_path, monkeypatch)
    api = project / "api.py"
    old = 'from fastapi import FastAPI\napp=FastAPI()\n@app.get("/v1/items")\ndef items(): return []\n'
    api.write_text(old, encoding="utf-8")
    from app.project_baselines import create_project_baseline
    from app.improvement_governance import evaluate_verified_candidate_governance

    create_project_baseline("demo", label="approved-v1")
    new = 'from fastapi import FastAPI\napp=FastAPI()\n@app.get("/v2/items")\ndef items(): return []\n'
    result = evaluate_verified_candidate_governance("demo", [{
        "action": "modify", "path": "api.py", "content": new,
        "expected_sha256": hashlib.sha256(old.encode()).hexdigest(),
    }])
    codes = {item["code"] for item in result["violations"]}
    assert result["passed"] is False
    assert "approved_api_contract_removed" in codes


def test_governance_enforces_required_and_protected_paths(tmp_path, monkeypatch):
    _, project = _workspace(tmp_path, monkeypatch)
    protected = project / "core.py"
    old = "VALUE = 1\n"
    protected.write_text(old, encoding="utf-8")
    from app.improvement_policy import save_improvement_policy, resolved_improvement_policy
    from app.improvement_governance import evaluate_verified_candidate_governance

    save_improvement_policy("demo", {
        "architecture": {
            "required_paths": ["core.py", "must_exist.py"],
            "protected_paths": ["core.py"],
        }
    })
    result = evaluate_verified_candidate_governance("demo", [{
        "action": "modify", "path": "core.py", "content": "VALUE = 2\n",
        "expected_sha256": hashlib.sha256(old.encode()).hexdigest(),
    }], policy_snapshot=resolved_improvement_policy("demo"))
    codes = {item["code"] for item in result["violations"]}
    assert "protected_path_change" in codes
    assert "required_path_missing" in codes


def test_repeated_candidate_is_suppressed_after_attempt_limit(tmp_path, monkeypatch):
    _, project = _workspace(tmp_path, monkeypatch)
    from app.candidate_suppression import apply_repeat_suppression
    from app.improvement_brain import generate_improvement_candidates
    from app.improvement_store import create_improvement_cycle, store_improvement_candidates, update_improvement_candidate

    snapshot = _finding_snapshot(project)
    for _ in range(2):
        cycle = create_improvement_cycle(project_name="demo", trigger="manual", policy="manual", request={})
        candidate = generate_improvement_candidates(snapshot, cycle_id=cycle["id"])[0]
        candidate = apply_repeat_suppression("demo", [candidate], repeat_limit=2)[0]
        saved = store_improvement_candidates(cycle["id"], [candidate])[0]
        update_improvement_candidate(saved["id"], status="validation_failed")

    fresh = generate_improvement_candidates(snapshot, cycle_id="fresh")[0]
    guarded = apply_repeat_suppression("demo", [fresh], repeat_limit=2)[0]
    assert guarded["repeat_count"] == 2
    assert guarded["suppressed"] is True
    assert guarded["suppression_reason"].startswith("repeated_candidate_limit")


def test_test_impact_memory_reuses_historical_checks_for_same_files(tmp_path, monkeypatch):
    _, project = _workspace(tmp_path, monkeypatch)
    from app.improvement_test_impact import enrich_candidates_with_test_impact, store_test_impact
    from app.improvement_brain import generate_improvement_candidates

    store_test_impact(
        cycle_id="cycle-1", candidate_id="candidate-1", issue_id="issue-1", project_name="demo",
        changed_files=["api.py"],
        validation={"passed": True, "checks": [{"args": ["python", "-m", "pytest", "-q", "tests/test_api.py"], "purpose": "API regression", "passed": True}]},
        quality_score=95,
    )
    candidate = generate_improvement_candidates(_finding_snapshot(project), cycle_id="cycle-2")[0]
    enriched = enrich_candidates_with_test_impact("demo", [candidate])[0]
    assert enriched["impact_memory"]["samples"] == 1
    assert any(check["args"][-1] == "tests/test_api.py" for check in enriched["validation_plan"])


def test_cancel_waiting_cycle_and_discard_non_winner_experiment(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app.improvement_store import (
        create_improvement_cycle, discard_improvement_experiment, request_improvement_cycle_cancel,
        store_improvement_experiment, update_improvement_cycle,
    )

    cycle = create_improvement_cycle(project_name="demo", trigger="manual", policy="manual", request={})
    update_improvement_cycle(cycle["id"], state="WAITING_SELECTION")
    cancelled = request_improvement_cycle_cancel(cycle["id"])
    assert cancelled["state"] == "CANCELLED"
    assert cancelled["completed_at"]

    cycle2 = create_improvement_cycle(project_name="demo", trigger="manual", policy="manual", request={})
    exp = store_improvement_experiment(
        cycle_id=cycle2["id"], candidate_id="candidate-x", issue_id="issue-x", experiment_rank=1,
        status="verified", quality_score=90, usage={}, result={},
    )
    discarded = discard_improvement_experiment(exp["id"])
    assert discarded["status"] == "discarded"
    assert discarded["discarded_at"]


@pytest.mark.asyncio
async def test_controller_rejects_verified_candidate_that_breaks_api_contract(tmp_path, monkeypatch):
    _, project = _workspace(tmp_path, monkeypatch)
    api = project / "api.py"
    old = 'from fastapi import FastAPI\napp=FastAPI()\n@app.get("/v1/items")\ndef items(): return []\n'
    api.write_text(old, encoding="utf-8")
    from app import improvement_controller as controller
    from app.improvement_store import create_improvement_cycle, get_improvement_cycle, list_improvement_candidates
    from app.project_baselines import create_project_baseline

    create_project_baseline("demo", label="approved")
    snapshot = _finding_snapshot(project)
    monkeypatch.setattr(controller, "capture_project_health", lambda *args, **kwargs: snapshot)

    async def fake_repair(issue, max_attempts=None, event_sink=None):
        new = 'from fastapi import FastAPI\napp=FastAPI()\n@app.get("/v2/items")\ndef items(): return []\n'
        return {
            "status": "verified", "issue_id": issue.issue_id, "attempts": [{"attempt_no": 1}],
            "proposed_changes": [{"action": "modify", "path": "api.py", "content": new, "expected_sha256": hashlib.sha256(old.encode()).hexdigest()}],
            "validation": {"passed": True, "checks": []}, "review": {"approved": True},
            "security": {"approved": True}, "quality": {"accepted": True, "score": 95},
        }

    monkeypatch.setattr(controller, "repair_issue", fake_repair)
    cycle = create_improvement_cycle(
        project_name="demo", trigger="manual", policy="manual",
        request={"run_checks": False, "allowed_risks": ["low", "medium"]},
    )
    await controller.run_improvement_cycle(cycle["id"])
    saved = get_improvement_cycle(cycle["id"])
    candidates = list_improvement_candidates(cycle["id"])
    assert saved["state"] == "VALIDATION_FAILED"
    assert candidates[0]["status"] == "governance_blocked"


def test_part6_routes_registered():
    from app.main import app
    paths = {route.path for route in app.routes}
    assert "/improvements/policies/{project_name}" in paths
    assert "/improvements/policies/{project_name}/history" in paths
    assert "/improvements/governance/checks" in paths
    assert "/improvements/test-impact" in paths
    assert "/improvements/cycles/{cycle_id}/cancel" in paths
    assert "/improvements/cycles/{cycle_id}/experiments/{experiment_id}/discard" in paths
