import json
import uuid
from datetime import datetime, timezone

import pytest

from app.config import settings
from app.database import get_db, init_database, insert_document, insert_chunk
from app.patch_engine import PatchError, validate_changes
from app.regression_detection import compare_debug_reports
from app.security_review import review_security


def _use_temp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "part2.db"))
    init_database()


def test_restored_missing_contracts_import():
    import app.search  # noqa: F401
    import app.qdrant_service  # noqa: F401
    import app.knowledge_gap_detection  # noqa: F401
    import app.rag_eval  # noqa: F401
    import app.regression_detection  # noqa: F401
    import app.change_timeline  # noqa: F401


def test_database_migrates_legacy_ingestion_columns(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    with get_db() as conn:
        docs = {r[1] for r in conn.execute("PRAGMA table_info(documents)").fetchall()}
        chunks = {r[1] for r in conn.execute("PRAGMA table_info(document_chunks)").fetchall()}
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"chunking_status", "embedding_status", "stored_filename", "extraction_status"}.issubset(docs)
    assert {"text", "content", "normalized_text_hash", "qdrant_error", "chunking_strategy"}.issubset(chunks)
    assert {"change_timeline", "knowledge_gap_reports", "rag_eval_sets", "rag_eval_runs", "regression_reports"}.issubset(tables)


def test_insert_document_normalizes_legacy_shape(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    doc_id = str(uuid.uuid4())
    insert_document({
        "id": doc_id,
        "stored_filename": "legacy.txt",
        "original_filename": "Legacy",
        "file_hash": doc_id,
        "file_size_bytes": 12,
        "mime_type": "text/plain",
        "status": "uploaded",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "chunking_status": "not_started",
    })
    with get_db() as conn:
        row = conn.execute("SELECT filename, stored_filename, file_size, file_size_bytes FROM documents WHERE id=?", (doc_id,)).fetchone()
    assert row["filename"] == "legacy.txt"
    assert row["file_size"] == 12
    assert row["file_size_bytes"] == 12


def test_patch_engine_blocks_protected_paths(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_PROTECTED_PATHS", ".env,.git/,data/ai_coder.db")
    with pytest.raises(PatchError):
        validate_changes([{"action": "modify", "path": ".env", "content": "SECRET=x"}])
    with pytest.raises(PatchError):
        validate_changes([{"action": "create", "path": ".git/config", "content": "x"}])
    validate_changes([{"action": "create", "path": ".env.example", "content": "SAFE=example"}])


def test_security_gate_rejects_high_risk_generated_code():
    result = review_security([{
        "action": "modify",
        "path": "runner.py",
        "content": "import subprocess\nsubprocess.run(cmd, shell=True)\n",
    }])
    assert result["approved"] is False
    assert result["counts"]["critical"] == 1


def test_regression_detection_classifies_known_metric_direction():
    baseline = {"coverage": 80, "error_count": 3, "issues": [{"id": "old"}]}
    current = {"coverage": 85, "error_count": 1, "issues": [{"id": "new"}]}
    regressions, improvements, unchanged = compare_debug_reports(baseline, current)
    assert any(i.get("type") == "new_issue" and i.get("key") == "new" for i in regressions)
    assert any(i.get("metric") == "coverage" for i in improvements)
    assert any(i.get("metric") == "error_count" for i in improvements)


def test_keyword_search_fallback_uses_legacy_text_column(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    doc_id = str(uuid.uuid4())
    insert_document({
        "id": doc_id, "filename": "guide.txt", "original_filename": "Guide",
        "file_hash": doc_id, "mime_type": "text/plain", "status": "uploaded",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    insert_chunk({
        "id": str(uuid.uuid4()), "document_id": doc_id, "chunk_index": 0,
        "text": "bounded recursive repair loop", "created_at": datetime.now(timezone.utc).isoformat(),
        "qdrant_status": "pending",
    })
    # Force vector path to fail before loading a model; fallback must remain useful.
    import app.embeddings as embeddings
    monkeypatch.setattr(embeddings, "get_embedding", lambda _q: (_ for _ in ()).throw(RuntimeError("offline")))
    from app.search import search_documents
    result = search_documents("recursive repair", limit=5)
    assert result["source"] == "keyword_fallback"
    assert result["results"]
    assert "bounded recursive repair loop" in result["results"][0]["content"]


def test_change_timeline_persists(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    from app.change_timeline import create_timeline_event, list_timeline_events
    event = create_timeline_event(event_type="test", title="Part 2", status="success", metadata={"ok": True})
    rows = list_timeline_events()
    assert rows[0]["id"] == event["id"]
    assert rows[0]["metadata"]["ok"] is True


def test_safe_command_policy_blocks_mutating_git(monkeypatch):
    from app.safe_commands import validate_args
    monkeypatch.setattr(settings, "AGENT_ALLOWED_EXECUTABLES", "git,python,pytest,npm,ruff,mypy")
    assert validate_args(["git", "status"]) == ["git", "status"]
    with pytest.raises(ValueError):
        validate_args(["git", "reset", "--hard"])
    with pytest.raises(ValueError):
        validate_args(["python", "-c", "__import__('os').remove('x')"])


def test_optional_modules_import_without_optional_packages():
    import app.planner  # noqa: F401
    import app.orchestrator  # noqa: F401
    import app.watcher  # noqa: F401
    import app.qdrant_store  # noqa: F401
    import app.embeddings  # noqa: F401

@pytest.mark.asyncio
async def test_repair_loop_retries_when_security_gate_rejects(tmp_path, monkeypatch):
    from app import coder as coder_module
    from app import repair_loop as repair_module
    from app.agent_runtime import AgentResult
    from app.security_review import review_security

    workspace = tmp_path / "workspace"
    project = workspace / "demo"
    project.mkdir(parents=True)
    (project / "runner.py").write_text("def run(cmd):\n    return cmd\n", encoding="utf-8")

    monkeypatch.setattr(settings, "WORKSPACE_ROOT", str(workspace))
    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "gate-retry.db"))
    monkeypatch.setattr(settings, "MAX_REPAIR_ATTEMPTS", 3)
    monkeypatch.setattr(settings, "AGENT_ALLOWED_EXECUTABLES", "python")
    init_database()
    calls = {"coder": 0}

    async def fake_coder(**kwargs):
        calls["coder"] += 1
        if calls["coder"] == 1:
            content = "import subprocess\ndef run(cmd):\n    return subprocess.run(cmd, shell=True)\n"
        else:
            content = "import subprocess\ndef run(cmd):\n    return subprocess.run(cmd, shell=False)\n"
        return {
            "status": "ok", "model": "fake", "warnings": [],
            "proposed_changes": [{"action": "modify", "path": "runner.py", "content": content}],
            "validation_plan": [{"args": ["python", "-m", "compileall", "-q", "."], "purpose": "compile"}],
        }

    async def fake_agent_run(name, context):
        if name == "debugger":
            return AgentResult("debugger", "ok", {"diagnosis": "security gate feedback", "next_strategy": "remove shell execution"})
        if name == "reviewer":
            return AgentResult("reviewer", "ok", {"approved": True, "risk": "low", "findings": []})
        if name == "security":
            data = review_security(context.evidence.get("changes", []))
            return AgentResult("security", "ok" if data["approved"] else "rejected", data)
        raise AssertionError(name)

    monkeypatch.setattr(coder_module, "draft_code_changes", fake_coder)
    monkeypatch.setattr(repair_module.agent_registry, "run", fake_agent_run)

    result = await repair_module.repair_issue(
        repair_module.RepairIssue(task="Run command without unsafe shell mode", project_name="demo", files=["runner.py"]),
        max_attempts=3,
    )
    assert result["status"] == "verified"
    assert len(result["attempts"]) == 2
    assert result["attempts"][0]["validation_result"]["status"] == "gate_failed"
    assert result["attempts"][0]["validation_result"]["security"]["approved"] is False
    assert result["security"]["approved"] is True
    assert "shell=False" in result["proposed_changes"][0]["content"]
    assert "shell=True" not in (project / "runner.py").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_planner_falls_back_without_llm(monkeypatch):
    from app import planner

    async def fail(*args, **kwargs):
        raise RuntimeError("model offline")

    monkeypatch.setattr(planner.model_manager, "generate_completion", fail)
    plan = await planner.create_plan("Add a safe feature")
    assert plan["fallback_used"] is True
    assert len(plan["phases"]) >= 1


def test_verified_repair_is_persisted_and_applied_exactly(tmp_path, monkeypatch):
    import hashlib
    from app.verified_candidate_store import store_verified_repair, get_verified_repair, apply_verified_repair

    workspace = tmp_path / "workspace"
    project = workspace / "demo"
    project.mkdir(parents=True)
    old = "value = 1\n"
    (project / "value.py").write_text(old, encoding="utf-8")
    monkeypatch.setattr(settings, "WORKSPACE_ROOT", str(workspace))
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "verified.db"))
    init_database()

    issue_id = str(uuid.uuid4())
    changes = [{
        "action": "modify", "path": "value.py", "content": "value = 2\n",
        "expected_sha256": hashlib.sha256(old.encode()).hexdigest(),
    }]
    store_verified_repair(
        issue_id=issue_id, project_name="demo", task="set value to 2", proposed_changes=changes,
        validation={"passed": True}, review={"approved": True},
        security={"approved": True, "counts": {}}, quality={"accepted": True, "score": 100},
    )
    saved = get_verified_repair(issue_id)
    assert saved["status"] == "verified"
    assert saved["proposed_changes"] == changes
    with pytest.raises(ValueError):
        apply_verified_repair(issue_id, confirm=False)
    applied = apply_verified_repair(issue_id, confirm=True)
    assert applied["status"] == "applied"
    assert applied["snapshot_id"]
    assert (project / "value.py").read_text(encoding="utf-8") == "value = 2\n"
    assert get_verified_repair(issue_id)["status"] == "applied"
