import uuid
from pathlib import Path

import pytest

from app.config import settings
from app.database import get_db, init_database


def _workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    project = workspace / "demo"
    project.mkdir(parents=True)
    monkeypatch.setattr(settings, "WORKSPACE_ROOT", str(workspace))
    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "ide.db"))
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(settings, "AGENT_ALLOWED_EXECUTABLES", ["python", "git", "pytest", "npm", "ruff", "mypy"])
    init_database()
    return workspace, project


def test_database_has_ide_session_tables(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    with get_db() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"ide_sessions", "ide_events"}.issubset(tables)


def test_test_discovery_finds_python_regression_suite(tmp_path, monkeypatch):
    _, project = _workspace(tmp_path, monkeypatch)
    (project / "app.py").write_text("x = 1\n", encoding="utf-8")
    tests = project / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")

    from app.test_discovery import discover_project_checks
    result = discover_project_checks(project, ["app.py"])
    quick_args = [item["args"] for item in result["quick_checks"]]
    regression_args = [item["args"] for item in result["regression_checks"]]
    assert ["python", "-m", "compileall", "-q", "."] in quick_args
    assert ["python", "-m", "pytest", "-q", "tests/test_app.py"] in quick_args
    assert ["python", "-m", "pytest", "-q"] in regression_args


def test_context_builder_collects_selection_diagnostics_and_related_test(tmp_path, monkeypatch):
    _, project = _workspace(tmp_path, monkeypatch)
    (project / "service.py").write_text("from helper import value\n\ndef read():\n    return value\n", encoding="utf-8")
    (project / "helper.py").write_text("value = 3\n", encoding="utf-8")
    (project / "tests").mkdir()
    (project / "tests" / "test_service.py").write_text("def test_service():\n    assert True\n", encoding="utf-8")

    from app.context_builder import build_ide_context
    result = build_ide_context(
        project_name="demo", current_file="service.py", selected_text="return value",
        diagnostics=[{"message": "example", "severity": "warning"}], terminal_output="trace line",
    )
    paths = {item["path"] for item in result["files"]}
    assert {"service.py", "helper.py", "tests/test_service.py"}.issubset(paths)
    assert result["selected_text"] == "return value"
    assert result["diagnostics"][0]["message"] == "example"
    assert result["terminal_output"] == "trace line"


def test_ide_store_persists_ordered_events(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app.ide_store import create_ide_session, append_ide_event, list_ide_events, update_ide_session, get_ide_session
    session = create_ide_session(mode="ask", project_name="demo", task="Explain", request={"mode": "ask"})
    append_ide_event(session["id"], "context_ready", stage="context", message="ready", payload={"files": 2})
    append_ide_event(session["id"], "answer_ready", stage="ask", message="done")
    events = list_ide_events(session["id"])
    assert [e["event_type"] for e in events][-2:] == ["context_ready", "answer_ready"]
    assert events[-2]["seq"] < events[-1]["seq"]
    update_ide_session(session["id"], status="completed", result={"answer": "ok"}, mark_completed=True)
    saved = get_ide_session(session["id"])
    assert saved["status"] == "completed"
    assert saved["result"]["answer"] == "ok"


@pytest.mark.asyncio
async def test_ask_mode_uses_project_context_and_finishes(tmp_path, monkeypatch):
    _, project = _workspace(tmp_path, monkeypatch)
    (project / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    from app import ide_service
    from app.ide_store import create_ide_session, get_ide_session, list_ide_events

    seen = {}
    async def fake_completion(prompt, **kwargs):
        seen["prompt"] = prompt
        return "add returns the sum of a and b"
    monkeypatch.setattr(ide_service.model_manager, "generate_completion", fake_completion)

    request = {"mode": "ask", "task": "What does add do?", "project_name": "demo", "current_file": "calc.py", "files": []}
    session = create_ide_session(mode="ask", project_name="demo", task=request["task"], request=request)
    result = await ide_service.run_ide_session(session["id"], request)
    assert result["answer"].startswith("add returns")
    assert "def add" in seen["prompt"]
    assert get_ide_session(session["id"])["status"] == "completed"
    event_types = [e["event_type"] for e in list_ide_events(session["id"])]
    assert "context_ready" in event_types
    assert "session_completed" in event_types


@pytest.mark.asyncio
async def test_repair_loop_emits_retry_events(tmp_path, monkeypatch):
    _, project = _workspace(tmp_path, monkeypatch)
    (project / "value.py").write_text("x = 0\n", encoding="utf-8")
    monkeypatch.setattr(settings, "MAX_REPAIR_ATTEMPTS", 3)

    from app import coder as coder_module
    from app import repair_loop as repair_module
    from app.agent_runtime import AgentResult

    calls = {"coder": 0}
    async def fake_coder(**kwargs):
        calls["coder"] += 1
        content = "x =\n" if calls["coder"] == 1 else "x = 2\n"
        return {
            "status": "ok", "model": "fake", "summary": "candidate",
            "proposed_changes": [{"action": "modify", "path": "value.py", "content": content}],
            "validation_plan": [{"args": ["python", "-m", "compileall", "-q", "."], "purpose": "compile"}],
        }
    async def fake_agent(name, context):
        if name == "debugger":
            return AgentResult("debugger", "ok", {"diagnosis": "fix it", "next_strategy": "minimal"})
        if name == "reviewer":
            return AgentResult("reviewer", "ok", {"approved": True, "risk": "low", "findings": []})
        if name == "security":
            return AgentResult("security", "ok", {"approved": True, "risk": "low", "findings": [], "counts": {"critical": 0, "high": 0, "medium": 0, "low": 0}})
        raise AssertionError(name)
    monkeypatch.setattr(coder_module, "draft_code_changes", fake_coder)
    monkeypatch.setattr(repair_module.agent_registry, "run", fake_agent)

    events = []
    result = await repair_module.repair_issue(
        repair_module.RepairIssue(task="set x to 2", project_name="demo", files=["value.py"]),
        max_attempts=3, event_sink=lambda kind, payload: events.append((kind, payload)),
    )
    assert result["status"] == "verified"
    event_types = [kind for kind, _ in events]
    assert event_types.count("attempt_started") == 2
    assert "attempt_failed" in event_types
    assert event_types[-1] == "repair_verified"


def test_apply_rolls_back_when_post_apply_verification_fails(tmp_path, monkeypatch):
    import hashlib
    _, project = _workspace(tmp_path, monkeypatch)
    old = "x = 1\n"
    (project / "value.py").write_text(old, encoding="utf-8")

    from app.verified_candidate_store import store_verified_repair, apply_verified_repair, get_verified_repair
    issue_id = str(uuid.uuid4())
    store_verified_repair(
        issue_id=issue_id, project_name="demo", task="bad candidate for rollback test",
        proposed_changes=[{
            "action": "modify", "path": "value.py", "content": "x =\n",
            "expected_sha256": hashlib.sha256(old.encode()).hexdigest(),
        }],
        validation={"passed": True, "checks": [{"args": ["python", "-m", "compileall", "-q", "."], "purpose": "compile"}]},
        review={"approved": True}, security={"approved": True, "counts": {}}, quality={"accepted": True, "score": 100},
    )
    result = apply_verified_repair(issue_id, confirm=True)
    assert result["status"] == "rolled_back"
    assert result["post_apply_validation"]["passed"] is False
    assert (project / "value.py").read_text(encoding="utf-8") == old
    saved = get_verified_repair(issue_id)
    assert saved["status"] == "rolled_back"
    assert saved["rollback_reason"]


def test_main_registers_ide_routes():
    from app.main import app
    paths = {route.path for route in app.routes}
    assert "/ide/sessions" in paths
    assert "/ide/sessions/{session_id}/events/stream" in paths
    assert "/ide/sessions/{session_id}/apply" in paths
    assert "/ide/test-discovery" in paths


def test_project_navigation_tree_search_and_symbols(tmp_path, monkeypatch):
    _, project = _workspace(tmp_path, monkeypatch)
    (project / "alpha.py").write_text("class Alpha:\n    pass\n\ndef calculate_total():\n    return 42\n", encoding="utf-8")
    (project / "README.md").write_text("The calculate_total helper returns a demo value.\n", encoding="utf-8")

    from app.project_navigation import repository_tree, search_project_text, search_symbols
    tree = repository_tree(project)
    assert {item["path"] for item in tree["files"]} >= {"alpha.py", "README.md"}
    text = search_project_text(project, "calculate_total")
    assert any(item["path"] == "alpha.py" for item in text["results"])
    symbols = search_symbols(project, "Alpha")
    assert any(item["name"] == "Alpha" and item["kind"] == "class" for item in symbols["matches"])


def test_main_registers_navigation_routes():
    from app.main import app
    paths = {route.path for route in app.routes}
    assert "/ide/tree" in paths
    assert "/ide/code-search" in paths
    assert "/ide/symbols" in paths
