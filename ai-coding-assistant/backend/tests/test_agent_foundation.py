import hashlib
from pathlib import Path

import pytest

from app.agent_runtime import AgentResult, agent_registry
from app.apply_changes import apply_drafted_changes
from app.candidate_workspace import CandidateWorkspace
from app.config import settings
from app.database import get_db, init_database
from app.patch_engine import PatchError, apply_changes, preview_changes
from app.safe_commands import run_safe_command


def test_agent_registry_has_core_roles():
    assert {"context", "planner", "coder", "debugger", "tester", "reviewer", "security", "architecture", "research"}.issubset(set(agent_registry.names()))


def test_candidate_workspace_is_isolated(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.py").write_text("x = 1\n", encoding="utf-8")
    with CandidateWorkspace.create(source) as candidate:
        (candidate.root / "a.py").write_text("x = 2\n", encoding="utf-8")
        assert (source / "a.py").read_text(encoding="utf-8") == "x = 1\n"
    assert not candidate.root.exists()


def test_patch_engine_blocks_traversal_and_stale_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MAX_PATCH_FILES", 12)
    monkeypatch.setattr(settings, "MAX_PATCH_BYTES", 500000)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(PatchError):
        apply_changes(tmp_path, [{"action": "modify", "path": "../escape.py", "content": "bad"}])
    with pytest.raises(PatchError):
        apply_changes(tmp_path, [{"action": "modify", "path": "a.py", "content": "x = 2\n", "expected_sha256": "deadbeef"}])


def test_patch_engine_preview_and_apply(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MAX_PATCH_FILES", 12)
    monkeypatch.setattr(settings, "MAX_PATCH_BYTES", 500000)
    old = "x = 1\n"
    (tmp_path / "a.py").write_text(old, encoding="utf-8")
    changes = [{
        "action": "modify", "path": "a.py", "content": "x = 2\n",
        "expected_sha256": hashlib.sha256(old.encode()).hexdigest(),
    }]
    preview = preview_changes(tmp_path, changes)
    assert "-x = 1" in preview[0].diff
    assert "+x = 2" in preview[0].diff
    result = apply_changes(tmp_path, changes)
    assert result[0].status == "success"
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 2\n"


def test_safe_commands_use_allowlist(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_ALLOWED_EXECUTABLES", ["python"])
    (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
    result = run_safe_command(tmp_path, ["python", "-m", "compileall", "-q", "."])
    assert result.passed
    with pytest.raises(ValueError):
        run_safe_command(tmp_path, ["python", "-c", "print('unsafe')"])
    with pytest.raises(ValueError):
        run_safe_command(tmp_path, ["bash", "-lc", "echo unsafe"])


def test_database_has_repair_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "test.db"))
    init_database()
    with get_db() as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"repair_attempts", "improvement_cycles", "improvement_candidates", "change_transactions"}.issubset(tables)


@pytest.mark.asyncio
async def test_repair_loop_retries_failed_validation_then_succeeds(tmp_path, monkeypatch):
    from app import coder as coder_module
    from app import repair_loop as repair_module

    workspace = tmp_path / "workspace"
    project = workspace / "demo"
    project.mkdir(parents=True)
    (project / "value.py").write_text("x = 0\n", encoding="utf-8")

    monkeypatch.setattr(settings, "WORKSPACE_ROOT", str(workspace))
    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "repair.db"))
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(settings, "MAX_REPAIR_ATTEMPTS", 3)
    monkeypatch.setattr(settings, "AGENT_ALLOWED_EXECUTABLES", ["python"])
    init_database()

    calls = {"coder": 0}

    async def fake_coder(**kwargs):
        calls["coder"] += 1
        content = "x =\n" if calls["coder"] == 1 else "x = 2\n"
        return {
            "status": "ok", "model": "fake", "warnings": [],
            "proposed_changes": [{"action": "modify", "path": "value.py", "content": content}],
            "validation_plan": [{"args": ["python", "-m", "compileall", "-q", "."], "cwd": None, "purpose": "compile"}],
        }

    async def fake_agent_run(name, context):
        if name == "debugger":
            return AgentResult("debugger", "ok", {"diagnosis": "syntax issue", "next_strategy": "fix syntax"})
        if name == "reviewer":
            return AgentResult("reviewer", "ok", {"approved": True, "risk": "low", "findings": []})
        if name == "security":
            return AgentResult("security", "ok", {"approved": True, "risk": "low", "findings": [], "counts": {"critical": 0, "high": 0, "medium": 0, "low": 0}})
        raise AssertionError(name)

    monkeypatch.setattr(coder_module, "draft_code_changes", fake_coder)
    monkeypatch.setattr(repair_module.agent_registry, "run", fake_agent_run)

    issue = repair_module.RepairIssue(task="Make value.py valid and set x to 2", project_name="demo", files=["value.py"])
    result = await repair_module.repair_issue(issue, max_attempts=3)

    assert result["status"] == "verified"
    assert len(result["attempts"]) == 2
    assert result["attempts"][0]["validation_result"]["passed"] is False
    assert result["attempts"][1]["validation_result"]["passed"] is True
    assert result["proposed_changes"][0]["content"] == "x = 2\n"
    # Live project must remain untouched until explicit approval/apply.
    assert (project / "value.py").read_text(encoding="utf-8") == "x = 0\n"


def test_apply_drafted_changes_creates_snapshot_and_updates_file(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "a.py").write_text("x=1\n", encoding="utf-8")
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path / "backups"))
    result = apply_drafted_changes([{"action": "modify", "path": "a.py", "content": "x=2\n"}], project)
    assert result[0]["status"] == "success"
    assert result[0]["snapshot_id"]
    assert (project / "a.py").read_text(encoding="utf-8") == "x=2\n"
