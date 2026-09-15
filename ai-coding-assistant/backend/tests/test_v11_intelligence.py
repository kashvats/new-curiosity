from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.adaptive_orchestration import route_task
from app.config import settings
from app.database import init_database
from app.experience_memory import record_experience, search_experiences
from app.repository_intelligence import rank_relevant_files
from app.v11_evaluation import record_benchmark_run, list_benchmark_runs


def _workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    project = workspace / "demo"
    project.mkdir(parents=True)
    monkeypatch.setattr(settings, "WORKSPACE_ROOT", str(workspace))
    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "v11.db"))
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path / "backups"))
    init_database()
    return workspace, project


def test_adaptive_router_skips_initial_debugger_for_bounded_feature():
    route = route_task("Add a small helper that formats user names", files=["names.py"])
    assert route.task_kind == "feature"
    assert route.needs_initial_debugger is False
    assert route.needs_planner is False
    assert "coder" in route.agent_sequence


def test_adaptive_router_escalates_debug_and_security():
    route = route_task(
        "Debug the authentication exception and unsafe token validation",
        evidence={"terminal_output": "Traceback: ValueError"},
    )
    assert route.needs_initial_debugger is True
    assert route.task_kind == "security"
    assert "debugger" in route.agent_sequence


def test_repository_intelligence_ranks_source_neighbors(tmp_path):
    project = tmp_path / "repo"
    (project / "app").mkdir(parents=True)
    (project / "tests").mkdir()
    (project / "app" / "auth.py").write_text(
        "from app.tokens import verify_token\n\ndef authenticate(token):\n    return verify_token(token)\n",
        encoding="utf-8",
    )
    (project / "app" / "tokens.py").write_text(
        "def verify_token(token):\n    return bool(token)\n",
        encoding="utf-8",
    )
    (project / "tests" / "test_auth.py").write_text(
        "from app.auth import authenticate\n\ndef test_auth():\n    assert authenticate('x')\n",
        encoding="utf-8",
    )
    result = rank_relevant_files(project, "Fix authenticate token verification regression", seed_files=["app/auth.py"], limit=5)
    assert result["selected_paths"][0] == "app/auth.py"
    assert "app/tokens.py" in result["selected_paths"]
    assert any(p.endswith("test_auth.py") for p in result["selected_paths"])


def test_contextual_experience_memory_prefers_related_task(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    record_experience(
        project_name="demo", issue_id="1", task="Fix JWT token expiry handling", strategy="refresh_claims",
        outcome="failed", failure_class="tests_failed", files=["auth.py"], lesson="Do not ignore timezone-aware expiry",
    )
    record_experience(
        project_name="demo", issue_id="2", task="Update dashboard heading", strategy="copy_edit",
        outcome="succeeded", files=["ui.jsx"], lesson="Simple copy update",
    )
    found = search_experiences(project_name="demo", task="JWT expiry bug in auth token", files=["auth.py"], limit=3)
    assert found
    assert found[0]["strategy"] == "refresh_claims"
    assert found[0]["outcome"] == "failed"


def test_experience_memory_deduplicates_and_counts_occurrences(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    kwargs = dict(
        project_name="demo", issue_id="1", task="Fix cache timeout", strategy="bounded_timeout",
        outcome="failed", failure_class="timeout", files=["cache.py"], lesson="Timeout too low",
    )
    record_experience(**kwargs)
    record_experience(**kwargs)
    found = search_experiences(project_name="demo", task="cache timeout", files=["cache.py"], limit=2)
    assert found[0]["occurrence_count"] == 2


def test_benchmark_tracking_measures_quality_and_cost(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    run = record_benchmark_run(
        version="1.1.0",
        suite_name="smoke",
        cases=[
            {"case_id": "a", "passed": True, "llm_calls": 3, "tokens": 1000, "duration_ms": 500, "files_changed": 2},
            {"case_id": "b", "passed": False, "regression": True, "llm_calls": 4, "tokens": 1400, "duration_ms": 700, "files_changed": 4},
        ],
    )
    assert run["summary"]["success_rate"] == 0.5
    assert run["summary"]["avg_llm_calls"] == 3.5
    saved = list_benchmark_runs(suite_name="smoke")
    assert saved[0]["id"] == run["id"]


@pytest.mark.asyncio
async def test_repair_skips_first_debugger_then_escalates_on_failure(tmp_path, monkeypatch):
    from app import coder as coder_module
    from app import repair_loop as repair_module
    from app.agent_runtime import AgentResult

    _, project = _workspace(tmp_path, monkeypatch)
    (project / "value.py").write_text("x = 0\n", encoding="utf-8")
    monkeypatch.setattr(settings, "MAX_REPAIR_ATTEMPTS", 3)
    monkeypatch.setattr(settings, "AGENT_ALLOWED_EXECUTABLES", "python")
    monkeypatch.setattr(settings, "V11_REPOSITORY_CONTEXT_ENABLED", False)

    calls = {"coder": 0, "debugger": 0}

    async def fake_coder(**kwargs):
        calls["coder"] += 1
        content = "x =\n" if calls["coder"] == 1 else "x = 2\n"
        return {
            "status": "ok", "model": "fake", "summary": "set value",
            "proposed_changes": [{"action": "modify", "path": "value.py", "content": content}],
            "validation_plan": [{"args": ["python", "-m", "compileall", "-q", "."], "purpose": "compile"}],
        }

    async def fake_agent(name, context):
        if name == "debugger":
            calls["debugger"] += 1
            return AgentResult("debugger", "ok", {"diagnosis": "syntax failure", "next_strategy": "fix syntax"})
        if name == "reviewer":
            return AgentResult("reviewer", "ok", {"approved": True, "risk": "low", "findings": []})
        if name == "security":
            return AgentResult("security", "ok", {"approved": True, "risk": "low", "findings": [], "counts": {"critical": 0, "high": 0, "medium": 0, "low": 0}})
        raise AssertionError(name)

    monkeypatch.setattr(coder_module, "draft_code_changes", fake_coder)
    monkeypatch.setattr(repair_module.agent_registry, "run", fake_agent)

    result = await repair_module.repair_issue(
        repair_module.RepairIssue(task="Set value to 2", project_name="demo", files=["value.py"]),
        max_attempts=3,
    )
    assert result["status"] == "verified"
    assert calls["debugger"] == 1
    assert result["attempts"][0]["debugger_invoked"] is False
    assert result["attempts"][1]["debugger_invoked"] is True
    assert result["attempts"][0]["diagnosis_source"] == "adaptive_router"


def test_v11_api_routes_registered():
    from app.main import app
    paths = {route.path for route in app.routes}
    assert "/v1.1/capabilities" in paths
    assert "/v1.1/routing/preview" in paths
    assert "/v1.1/repository/context" in paths
    assert "/v1.1/experiences/search" in paths
    assert "/v1.1/evaluation/benchmarks" in paths

@pytest.mark.asyncio
async def test_model_usage_telemetry_records_sizes_without_prompt_content(tmp_path, monkeypatch):
    from app.model_manager import ModelManager
    from app.model_usage import model_usage_summary

    _workspace(tmp_path, monkeypatch)
    manager = ModelManager()

    async def fake_ollama(prompt, model, temperature, max_tokens, system_prompt, expect_json=False, _is_fallback=False):
        return "small answer"

    monkeypatch.setattr(manager, "_call_ollama", fake_ollama)
    result = await manager.generate_completion("secret prompt contents", model="local-test")
    assert result == "small answer"
    summary = model_usage_summary()
    assert summary["calls_sampled"] >= 1
    assert summary["models"][0]["estimated_input_tokens"] > 0
    # Usage table is intentionally aggregate/metadata only; no prompt field exists.
    from app.database import get_db
    with get_db() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(v11_model_usage)").fetchall()}
    assert "prompt" not in cols
    await manager.aclose()

@pytest.mark.asyncio
async def test_orchestrator_skips_planner_for_simple_bounded_task(tmp_path, monkeypatch):
    from app import orchestrator

    _, project = _workspace(tmp_path, monkeypatch)
    (project / "names.py").write_text("def name(x):\n    return x\n", encoding="utf-8")

    async def planner_should_not_run(*args, **kwargs):
        raise AssertionError("planner should be skipped for a simple bounded task")

    async def fake_repair(issue):
        return {
            "status": "verified",
            "attempts": [],
            "quality": {"accepted": True, "score": 1.0},
            "proposed_changes": [],
        }

    monkeypatch.setattr(orchestrator, "create_plan", planner_should_not_run)
    monkeypatch.setattr(orchestrator, "repair_issue", fake_repair)
    result = await orchestrator.run_orchestrator(
        "Add a small helper to format names",
        ["names.py"],
        project_name="demo",
        auto_apply=False,
    )
    assert result["status"] == "waiting_approval"
    assert result["plan"]["planner_skipped"] is True
    assert result["adaptive_route"]["needs_planner"] is False


def test_context_builder_includes_ranked_repository_intelligence(tmp_path, monkeypatch):
    from app.context_builder import build_ide_context

    _, project = _workspace(tmp_path, monkeypatch)
    (project / "auth.py").write_text("from tokens import verify_token\n\ndef authenticate(x): return verify_token(x)\n", encoding="utf-8")
    (project / "tokens.py").write_text("def verify_token(x): return bool(x)\n", encoding="utf-8")
    context = build_ide_context(
        project_name="demo",
        current_file="auth.py",
        task="Fix authenticate token verification",
    )
    assert context["repository_intelligence"]["selected_paths"]
    assert "auth.py" in context["requested_files"]
    assert any(item["path"] == "tokens.py" for item in context["files"])


def test_benchmark_comparison_shows_quality_and_efficiency_delta(tmp_path, monkeypatch):
    from app.v11_evaluation import compare_benchmark_versions

    _workspace(tmp_path, monkeypatch)
    record_benchmark_run(
        version="1.0.0", suite_name="compare",
        cases=[{"case_id": "a", "passed": True, "llm_calls": 6, "tokens": 3000, "duration_ms": 1000, "files_changed": 3}],
    )
    record_benchmark_run(
        version="1.1.0", suite_name="compare",
        cases=[{"case_id": "a", "passed": True, "llm_calls": 4, "tokens": 2200, "duration_ms": 700, "files_changed": 2}],
    )
    result = compare_benchmark_versions(suite_name="compare", baseline_version="1.0.0", candidate_version="1.1.0")
    assert result["deltas_candidate_minus_baseline"]["avg_llm_calls"] == -2.0
    assert result["improved"]["avg_tokens"] is True
