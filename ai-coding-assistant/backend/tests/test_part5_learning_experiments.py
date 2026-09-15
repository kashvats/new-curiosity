import json

import pytest

from app.config import settings
from app.database import get_db, init_database


def _workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    project = workspace / "demo"
    project.mkdir(parents=True)
    monkeypatch.setattr(settings, "WORKSPACE_ROOT", str(workspace))
    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "part5.db"))
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(settings, "AGENT_ALLOWED_EXECUTABLES", "python,pytest,git,npm,ruff,mypy")
    init_database()
    return workspace, project


def _snapshot(score=70.0, two=False):
    findings = [{
        "category": "knowledge", "severity": "low", "code": "missing_readme",
        "message": "Project README is missing.", "likely_files": ["README.md"],
        "suggested_task": "Create a concise README using repository facts.",
        "risk": "low", "benefit": 0.5, "confidence": 0.95, "urgency": 0.5,
        "estimated_cost": 0.5, "validation_plan": [],
    }]
    if two:
        findings.append({
            "category": "dependencies", "severity": "medium", "code": "node_missing_lockfile",
            "message": "Lockfile missing.", "likely_files": ["package.json"],
            "suggested_task": "Add the existing package manager lockfile.",
            "risk": "medium", "benefit": 0.8, "confidence": 0.95, "urgency": 0.7,
            "estimated_cost": 0.6, "validation_plan": [],
        })
    return {
        "project_name": "demo", "project_root": "/tmp/demo", "health_score": score,
        "dimensions": {"tests": 80, "security": 100, "architecture": 80, "quality": 80, "knowledge": 50, "dependencies": 80, "drift": 100},
        "findings": findings,
        "checks": {"passed": True, "checks": [], "plan": []},
        "metadata": {"source_files": 1},
    }


def test_part5_schema_adds_learning_experiment_baseline_and_budget_state(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    with get_db() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        cycles = {row[1] for row in conn.execute("PRAGMA table_info(improvement_cycles)").fetchall()}
        candidates = {row[1] for row in conn.execute("PRAGMA table_info(improvement_candidates)").fetchall()}
    assert {"improvement_experiments", "project_baselines"}.issubset(tables)
    assert {"budget_json", "usage_json"}.issubset(cycles)
    assert {"strategy_key", "base_priority_score", "learning_multiplier", "history_samples"}.issubset(candidates)


def test_dependency_health_detects_unpinned_and_missing_lockfile(tmp_path, monkeypatch):
    _, project = _workspace(tmp_path, monkeypatch)
    (project / "requirements.txt").write_text("fastapi>=0.100\nuvicorn==0.30.0\n", encoding="utf-8")
    (project / "package.json").write_text(json.dumps({"dependencies": {"react": "latest"}}), encoding="utf-8")
    from app.dependency_health import analyze_dependency_health
    result = analyze_dependency_health(project)
    codes = {item["code"] for item in result["findings"]}
    assert "python_unpinned_dependencies" in codes
    assert "node_unbounded_dependencies" in codes
    assert "node_missing_lockfile" in codes
    assert result["score"] < 100
    assert result["metadata"]["network_used"] is False


def test_api_contract_baseline_detects_removed_route(tmp_path, monkeypatch):
    _, project = _workspace(tmp_path, monkeypatch)
    api = project / "api.py"
    api.write_text('from fastapi import FastAPI\napp=FastAPI()\n@app.get("/v1/items")\ndef items(): return []\n', encoding="utf-8")
    from app.project_baselines import create_project_baseline, project_drift
    baseline = create_project_baseline("demo", label="v1")
    assert "GET /v1/items" in baseline["payload"]["api_routes"]
    api.write_text('from fastapi import FastAPI\napp=FastAPI()\n@app.get("/v2/items")\ndef items(): return []\n', encoding="utf-8")
    drift = project_drift("demo")
    assert drift["status"] == "compared"
    assert "GET /v1/items" in drift["api"]["removed"]
    assert "GET /v2/items" in drift["api"]["added"]
    assert drift["score"] < 100


def test_outcome_history_conservatively_re_ranks_matching_strategy(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "IMPROVEMENT_MIN_LEARNING_SAMPLES", 3)
    from app.improvement_brain import generate_improvement_candidates
    from app.improvement_learning import apply_outcome_learning, strategy_statistics
    from app.improvement_store import create_improvement_cycle, store_improvement_candidates, store_improvement_outcome

    for i, delta in enumerate((8.0, 10.0, 12.0), start=1):
        cycle = create_improvement_cycle(project_name="demo", trigger="manual", policy="manual", request={})
        candidate = generate_improvement_candidates(_snapshot(), cycle_id=cycle["id"])[0]
        saved = store_improvement_candidates(cycle["id"], [candidate])[0]
        store_improvement_outcome(
            cycle_id=cycle["id"], candidate_id=saved["id"], issue_id=f"issue-{i}", project_name="demo",
            apply_status="applied", baseline_score=70, final_score=70 + delta,
            baseline_snapshot_id=None, final_snapshot_id=None, details={},
        )

    fresh = generate_improvement_candidates(_snapshot(), cycle_id="new")[0]
    learned = apply_outcome_learning("demo", [fresh])[0]
    assert learned["history_samples"] == 3
    assert learned["learning_multiplier"] > 1.0
    assert learned["priority_score"] > learned["base_priority_score"]
    stats = strategy_statistics(project_name="demo")
    assert stats[0]["successes"] == 3
    assert stats[0]["average_score_delta"] == 10.0


@pytest.mark.asyncio
async def test_cycle_can_pause_for_manual_candidate_selection_then_resume(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app import improvement_controller as controller
    from app.improvement_store import create_improvement_cycle, get_improvement_cycle, list_improvement_candidates

    monkeypatch.setattr(controller, "capture_project_health", lambda *args, **kwargs: _snapshot(two=True))
    calls = {"repair": 0}

    async def fake_repair(issue, max_attempts=None, event_sink=None):
        calls["repair"] += 1
        return {
            "status": "verified", "issue_id": issue.issue_id,
            "attempts": [{"attempt_no": 1}], "proposed_changes": [],
            "validation": {"passed": True}, "review": {"approved": True},
            "security": {"approved": True}, "quality": {"accepted": True, "score": 91},
        }

    monkeypatch.setattr(controller, "repair_issue", fake_repair)
    cycle = create_improvement_cycle(
        project_name="demo", trigger="manual", policy="manual",
        request={"run_checks": False, "allowed_risks": ["low", "medium"], "pause_for_candidate_selection": True},
    )
    await controller.run_improvement_cycle(cycle["id"])
    paused = get_improvement_cycle(cycle["id"])
    assert paused["state"] == "WAITING_SELECTION"
    assert calls["repair"] == 0
    candidates = list_improvement_candidates(cycle["id"])
    chosen = candidates[-1]["id"]

    await controller.select_improvement_candidate_for_cycle(cycle["id"], chosen)
    resumed = get_improvement_cycle(cycle["id"])
    assert resumed["state"] == "WAITING_APPROVAL"
    assert resumed["selected_candidate_id"] == chosen
    assert calls["repair"] == 1


@pytest.mark.asyncio
async def test_experiment_mode_selects_highest_quality_verified_candidate(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app import improvement_controller as controller
    from app.improvement_store import create_improvement_cycle, get_improvement_cycle, list_improvement_candidates, list_improvement_experiments

    monkeypatch.setattr(controller, "capture_project_health", lambda *args, **kwargs: _snapshot(two=True))

    async def fake_repair(issue, max_attempts=None, event_sink=None):
        score = 99 if "README" in issue.task else 82
        return {
            "status": "verified", "issue_id": issue.issue_id,
            "attempts": [{"attempt_no": 1}], "proposed_changes": [],
            "validation": {"passed": True}, "review": {"approved": True},
            "security": {"approved": True}, "quality": {"accepted": True, "score": score},
        }

    monkeypatch.setattr(controller, "repair_issue", fake_repair)
    cycle = create_improvement_cycle(
        project_name="demo", trigger="manual", policy="manual",
        request={
            "run_checks": False, "allowed_risks": ["low", "medium"],
            "pause_for_candidate_selection": True, "experiment_mode": True, "experiment_candidates": 2,
            "max_candidate_repairs": 2, "max_cycle_attempts": 4,
        },
    )
    await controller.run_improvement_cycle(cycle["id"])
    candidates = list_improvement_candidates(cycle["id"])
    # Start with the non-README candidate; experiment mode is allowed to choose the
    # better independently verified result.
    non_readme = next(item for item in candidates if "README" not in item["proposal"])
    await controller.select_improvement_candidate_for_cycle(cycle["id"], non_readme["id"], experiment_mode=True, experiment_candidates=2)
    saved = get_improvement_cycle(cycle["id"])
    winner = next(item for item in list_improvement_candidates(cycle["id"]) if item["id"] == saved["selected_candidate_id"])
    assert saved["state"] == "WAITING_APPROVAL"
    assert "README" in winner["proposal"]
    experiments = list_improvement_experiments(cycle["id"])
    assert len(experiments) == 2
    assert max(item["quality_score"] for item in experiments) == 99


@pytest.mark.asyncio
async def test_experiment_cycle_stops_when_attempt_budget_is_exhausted(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app import improvement_controller as controller
    from app.improvement_store import create_improvement_cycle, get_improvement_cycle, list_improvement_candidates

    monkeypatch.setattr(controller, "capture_project_health", lambda *args, **kwargs: _snapshot(two=True))

    async def fake_repair(issue, max_attempts=None, event_sink=None):
        return {
            "status": "verified", "issue_id": issue.issue_id,
            "attempts": [{"attempt_no": 1}], "proposed_changes": [],
            "validation": {"passed": True}, "review": {"approved": True},
            "security": {"approved": True}, "quality": {"accepted": True, "score": 90},
        }

    monkeypatch.setattr(controller, "repair_issue", fake_repair)
    cycle = create_improvement_cycle(
        project_name="demo", trigger="manual", policy="manual",
        request={
            "run_checks": False, "allowed_risks": ["low", "medium"], "pause_for_candidate_selection": True,
            "experiment_mode": True, "experiment_candidates": 2,
            "max_candidate_repairs": 2, "max_cycle_attempts": 1,
        },
    )
    await controller.run_improvement_cycle(cycle["id"])
    first = list_improvement_candidates(cycle["id"])[0]
    await controller.select_improvement_candidate_for_cycle(cycle["id"], first["id"], experiment_mode=True, experiment_candidates=2)
    saved = get_improvement_cycle(cycle["id"])
    assert saved["state"] == "BUDGET_EXCEEDED"
    assert saved["completed_at"]
    assert saved["usage"]["attempts"] == 1


def test_part5_routes_registered():
    from app.main import app
    paths = {route.path for route in app.routes}
    assert "/improvements/cycles/{cycle_id}/select" in paths
    assert "/improvements/cycles/{cycle_id}/experiments" in paths
    assert "/improvements/learning/strategies" in paths
    assert "/improvements/baselines" in paths
    assert "/improvements/drift" in paths
    assert "/improvements/dependencies" in paths
