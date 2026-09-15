import hashlib
import uuid

import pytest

from app.config import settings
from app.database import get_db, init_database


def _workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    project = workspace / "demo"
    project.mkdir(parents=True)
    monkeypatch.setattr(settings, "WORKSPACE_ROOT", str(workspace))
    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "part4.db"))
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(settings, "AGENT_ALLOWED_EXECUTABLES", "python,pytest,git,npm,ruff,mypy")
    init_database()
    return workspace, project


def _snapshot(score=70.0):
    return {
        "project_name": "demo",
        "project_root": "/tmp/demo",
        "health_score": score,
        "dimensions": {"tests": 60, "security": 100, "architecture": 70, "quality": 75, "knowledge": 45},
        "findings": [{
            "category": "knowledge",
            "severity": "low",
            "code": "missing_readme",
            "message": "Project README is missing.",
            "likely_files": ["README.md"],
            "suggested_task": "Create a concise README using repository facts.",
            "risk": "low",
            "benefit": 0.5,
            "confidence": 0.95,
            "urgency": 0.5,
            "estimated_cost": 0.5,
            "validation_plan": [{"args": ["python", "-m", "compileall", "-q", "."], "purpose": "compile"}],
        }],
        "checks": {"passed": True, "checks": [], "plan": [{"args": ["python", "-m", "compileall", "-q", "."]}]},
        "metadata": {"source_files": 1},
    }


def test_part4_database_tables_and_columns(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    with get_db() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        cycle_columns = {row[1] for row in conn.execute("PRAGMA table_info(improvement_cycles)").fetchall()}
        candidate_columns = {row[1] for row in conn.execute("PRAGMA table_info(improvement_candidates)").fetchall()}
    assert {"project_health_snapshots", "improvement_events", "improvement_outcomes"}.issubset(tables)
    assert {"policy", "baseline_snapshot_id", "final_snapshot_id", "selected_issue_id", "request_json", "result_json"}.issubset(cycle_columns)
    assert {"urgency", "priority_score", "likely_files_json", "validation_plan_json", "issue_id"}.issubset(candidate_columns)


def test_improvement_agent_registered():
    from app.agent_runtime import agent_registry
    assert "improvement" in agent_registry.names()


def test_priority_prefers_high_benefit_low_risk_candidate():
    from app.improvement_brain import generate_improvement_candidates, select_improvement_candidate
    snapshot = _snapshot()
    snapshot["findings"].append({
        "category": "security", "severity": "high", "code": "x", "message": "High-risk issue",
        "suggested_task": "Do risky thing", "likely_files": ["a.py"], "risk": "high",
        "benefit": 1.0, "confidence": 0.99, "urgency": 1.0, "estimated_cost": 0.5,
    })
    candidates = generate_improvement_candidates(snapshot, cycle_id="cycle")
    selected = select_improvement_candidate(candidates, allowed_risks=["low", "medium"])
    assert selected is not None
    assert selected["risk"] == "low"
    assert selected["proposal"].startswith("Create a concise README")
    assert all(item["priority_score"] >= 0 for item in candidates)


def test_project_health_captures_passing_machine_checks(tmp_path, monkeypatch):
    _, project = _workspace(tmp_path, monkeypatch)
    (project / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (project / "README.md").write_text("# Demo\n", encoding="utf-8")
    tests = project / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n", encoding="utf-8")
    from app.project_health import capture_project_health
    result = capture_project_health("demo", run_checks=True)
    assert result["checks"]["passed"] is True
    assert result["dimensions"]["tests"] == 100.0
    assert result["health_score"] > 80
    assert result["metadata"]["source_files"] >= 2


@pytest.mark.asyncio
async def test_observe_only_cycle_generates_candidates_without_repair(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app import improvement_controller as controller
    from app.improvement_store import create_improvement_cycle, get_improvement_cycle, list_improvement_candidates

    monkeypatch.setattr(controller, "capture_project_health", lambda *args, **kwargs: _snapshot())

    async def should_not_run(*args, **kwargs):
        raise AssertionError("observe_only must not enter repair loop")

    monkeypatch.setattr(controller, "repair_issue", should_not_run)
    cycle = create_improvement_cycle(
        project_name="demo", trigger="manual", policy="observe_only",
        request={"policy": "observe_only", "run_checks": False, "allowed_risks": ["low", "medium"]},
    )
    await controller.run_improvement_cycle(cycle["id"])
    saved = get_improvement_cycle(cycle["id"])
    assert saved["state"] == "IDLE"
    assert saved["completed_at"]
    assert saved["stop_reason"] == "observe_only"
    candidates = list_improvement_candidates(cycle["id"])
    assert candidates
    assert any(item["status"] == "selected" for item in candidates)


@pytest.mark.asyncio
async def test_manual_cycle_prepares_verified_repair_and_waits_for_approval(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app import improvement_controller as controller
    from app.improvement_store import create_improvement_cycle, get_improvement_cycle, list_improvement_candidates

    monkeypatch.setattr(controller, "capture_project_health", lambda *args, **kwargs: _snapshot())

    async def fake_repair(issue, max_attempts=None, event_sink=None):
        if event_sink:
            event_sink("attempt_started", {"attempt_no": 1})
            event_sink("repair_verified", {"issue_id": issue.issue_id})
        return {
            "status": "verified", "issue_id": issue.issue_id, "proposed_changes": [],
            "validation": {"passed": True}, "review": {"approved": True},
            "security": {"approved": True}, "quality": {"accepted": True, "score": 95},
            "requires_approval": True,
        }

    monkeypatch.setattr(controller, "repair_issue", fake_repair)
    cycle = create_improvement_cycle(
        project_name="demo", trigger="manual", policy="manual",
        request={"policy": "manual", "run_checks": False, "allowed_risks": ["low", "medium"]},
    )
    await controller.run_improvement_cycle(cycle["id"])
    saved = get_improvement_cycle(cycle["id"])
    assert saved["state"] == "WAITING_APPROVAL"
    assert saved["selected_issue_id"]
    assert saved["completed_at"] is None
    selected = [item for item in list_improvement_candidates(cycle["id"]) if item["status"] == "verified"]
    assert len(selected) == 1
    assert selected[0]["issue_id"] == saved["selected_issue_id"]


def test_apply_cycle_records_outcome_and_final_health(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app import improvement_controller as controller
    from app.improvement_brain import generate_improvement_candidates
    from app.improvement_store import (
        create_improvement_cycle, get_improvement_cycle, list_improvement_outcomes,
        store_health_snapshot, store_improvement_candidates, update_improvement_candidate, update_improvement_cycle,
    )

    cycle = create_improvement_cycle(project_name="demo", trigger="manual", policy="manual", request={"policy": "manual"})
    baseline = _snapshot(70.0)
    baseline_row = store_health_snapshot(project_name="demo", snapshot=baseline, cycle_id=cycle["id"], phase="baseline")
    candidate = generate_improvement_candidates(baseline, cycle_id=cycle["id"])[0]
    candidate = store_improvement_candidates(cycle["id"], [candidate])[0]
    issue_id = str(uuid.uuid4())
    update_improvement_candidate(candidate["id"], status="verified", issue_id=issue_id)
    update_improvement_cycle(
        cycle["id"], state="WAITING_APPROVAL", baseline_score=70.0,
        baseline_snapshot_id=baseline_row["id"], selected_candidate_id=candidate["id"], selected_issue_id=issue_id,
    )
    monkeypatch.setattr(controller, "apply_verified_repair", lambda *args, **kwargs: {"status": "applied", "issue_id": issue_id, "snapshot_id": "snap-1"})
    final = _snapshot(82.0)
    final["findings"] = []
    monkeypatch.setattr(controller, "capture_project_health", lambda *args, **kwargs: final)

    result = controller.apply_improvement_cycle(cycle["id"], confirm=True)
    assert result["state"] == "IDLE"
    assert result["completed_at"]
    assert result["final_score"] == 82.0
    outcomes = list_improvement_outcomes(cycle_id=cycle["id"])
    assert outcomes[0]["apply_status"] == "applied"
    assert outcomes[0]["score_delta"] == 12.0


def test_health_regression_triggers_snapshot_rollback(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app import improvement_controller as controller
    from app.improvement_brain import generate_improvement_candidates
    from app.improvement_store import create_improvement_cycle, store_health_snapshot, store_improvement_candidates, update_improvement_candidate, update_improvement_cycle

    cycle = create_improvement_cycle(project_name="demo", trigger="manual", policy="manual", request={"policy": "manual"})
    baseline = _snapshot(80.0)
    baseline_row = store_health_snapshot(project_name="demo", snapshot=baseline, cycle_id=cycle["id"], phase="baseline")
    candidate = store_improvement_candidates(cycle["id"], [generate_improvement_candidates(baseline, cycle_id=cycle["id"])[0]])[0]
    issue_id = str(uuid.uuid4())
    update_improvement_candidate(candidate["id"], status="verified", issue_id=issue_id)
    update_improvement_cycle(cycle["id"], state="WAITING_APPROVAL", baseline_score=80.0, baseline_snapshot_id=baseline_row["id"], selected_candidate_id=candidate["id"], selected_issue_id=issue_id)
    monkeypatch.setattr(controller, "apply_verified_repair", lambda *args, **kwargs: {"status": "applied", "snapshot_id": "snap"})
    calls = {"health": 0, "rollback": 0}

    def health(*args, **kwargs):
        calls["health"] += 1
        return _snapshot(60.0 if calls["health"] == 1 else 80.0)

    def rollback(*args, **kwargs):
        calls["rollback"] += 1
        return {"status": "rolled_back", "snapshot_id": "snap"}

    monkeypatch.setattr(controller, "capture_project_health", health)
    monkeypatch.setattr(controller, "rollback_applied_repair", rollback)
    monkeypatch.setattr(settings, "IMPROVEMENT_MAX_SCORE_REGRESSION", 3.0)
    result = controller.apply_improvement_cycle(cycle["id"], confirm=True)
    assert result["state"] == "ROLLBACK_REQUIRED"
    assert calls["rollback"] == 1
    assert result["final_score"] == 80.0


def test_explicit_rollback_restores_applied_verified_repair(tmp_path, monkeypatch):
    _, project = _workspace(tmp_path, monkeypatch)
    old = "value = 1\n"
    (project / "value.py").write_text(old, encoding="utf-8")
    from app.verified_candidate_store import apply_verified_repair, rollback_applied_repair, store_verified_repair, get_verified_repair
    issue_id = str(uuid.uuid4())
    store_verified_repair(
        issue_id=issue_id, project_name="demo", task="change value",
        proposed_changes=[{
            "action": "modify", "path": "value.py", "content": "value = 2\n",
            "expected_sha256": hashlib.sha256(old.encode()).hexdigest(),
        }],
        validation={"passed": True, "checks": [{"args": ["python", "-m", "compileall", "-q", "."], "purpose": "compile"}]},
        review={"approved": True}, security={"approved": True}, quality={"accepted": True, "score": 95},
    )
    applied = apply_verified_repair(issue_id, confirm=True)
    assert applied["status"] == "applied"
    assert (project / "value.py").read_text(encoding="utf-8") == "value = 2\n"
    rolled = rollback_applied_repair(issue_id, reason="test rollback")
    assert rolled["status"] == "rolled_back"
    assert (project / "value.py").read_text(encoding="utf-8") == old
    assert get_verified_repair(issue_id)["status"] == "rolled_back"


def test_main_registers_improvement_routes():
    from app.main import app
    paths = {route.path for route in app.routes}
    assert "/improvements/health" in paths
    assert "/improvements/cycles" in paths
    assert "/improvements/cycles/{cycle_id}/apply" in paths
    assert "/improvements/outcomes" in paths
    assert "/agents/repairs/{issue_id}/rollback" in paths
