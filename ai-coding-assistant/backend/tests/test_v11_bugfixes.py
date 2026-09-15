from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.config import settings


class _PostClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.models = []

    async def post(self, url, json=None, **kwargs):
        self.models.append((json or {}).get("model"))
        status, data = self.payloads.pop(0)
        request = httpx.Request("POST", url)
        return httpx.Response(status, json=data, request=request)

    async def aclose(self):
        return None


class _StreamResponse:
    def __init__(self, status: int, lines=()):
        self.status_code = status
        self._lines = list(lines)
        self.request = httpx.Request("POST", "http://ollama/api/generate")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _StreamContext:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _StreamClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.models = []

    def stream(self, method, url, json=None, **kwargs):
        self.models.append((json or {}).get("model"))
        return _StreamContext(self.responses.pop(0))

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_ollama_generate_404_fallback_releases_semaphore(monkeypatch):
    from app import model_manager as mm

    manager = mm.ModelManager()
    await manager._ollama_client.aclose()
    fake = _PostClient([
        (404, {"error": "missing"}),
        (200, {"response": "fallback-ok"}),
    ])
    manager._ollama_client = fake
    monkeypatch.setattr(settings, "PLANNER_MODEL", "fallback-model")
    monkeypatch.setattr(manager, "_trigger_background_pull", lambda model: None)

    result = await asyncio.wait_for(
        manager._call_ollama("hello", "missing-model", 0.1, 100, None),
        timeout=1.0,
    )
    assert result == "fallback-ok"
    assert fake.models == ["missing-model", "fallback-model"]
    await manager.aclose()


@pytest.mark.asyncio
async def test_ollama_chat_404_fallback_releases_semaphore(monkeypatch):
    from app import model_manager as mm

    manager = mm.ModelManager()
    await manager._ollama_client.aclose()
    fake = _PostClient([
        (404, {"error": "missing"}),
        (200, {"message": {"role": "assistant", "content": "ok"}}),
    ])
    manager._ollama_client = fake
    monkeypatch.setattr(settings, "PLANNER_MODEL", "fallback-model")
    monkeypatch.setattr(manager, "_trigger_background_pull", lambda model: None)

    result = await asyncio.wait_for(
        manager._chat_ollama_with_tools([{"role": "user", "content": "hi"}], None, "missing-model", 0.1),
        timeout=1.0,
    )
    assert result["content"] == "ok"
    assert fake.models == ["missing-model", "fallback-model"]
    await manager.aclose()


@pytest.mark.asyncio
async def test_ollama_stream_404_fallback_releases_semaphore(monkeypatch):
    from app import model_manager as mm

    manager = mm.ModelManager()
    await manager._ollama_client.aclose()
    fake = _StreamClient([
        _StreamResponse(404),
        _StreamResponse(200, ['{"response":"A"}', '{"response":"B"}']),
    ])
    manager._ollama_client = fake
    monkeypatch.setattr(settings, "PLANNER_MODEL", "fallback-model")
    monkeypatch.setattr(manager, "_trigger_background_pull", lambda model: None)

    async def collect():
        return [chunk async for chunk in manager._call_ollama_stream("hello", "missing-model", 0.1, 100, None)]

    chunks = await asyncio.wait_for(collect(), timeout=1.0)
    assert chunks == ["A", "B"]
    assert fake.models == ["missing-model", "fallback-model"]
    await manager.aclose()


def test_repository_relative_import_resolves_within_correct_package(tmp_path):
    from app.repository_intelligence import build_repository_graph, clear_repository_graph_cache

    for package in ("a_pkg", "z_pkg"):
        pkg = tmp_path / package
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "shared.py").write_text(f"PACKAGE = {package!r}\n", encoding="utf-8")
    (tmp_path / "z_pkg" / "feature.py").write_text("from .shared import PACKAGE\n", encoding="utf-8")

    clear_repository_graph_cache(tmp_path)
    graph = build_repository_graph(tmp_path)
    assert "z_pkg/shared.py" in graph["edges"]["z_pkg/feature.py"]
    assert "a_pkg/shared.py" not in graph["edges"]["z_pkg/feature.py"]


def test_context_builder_local_neighbor_resolves_python_relative_import(tmp_path):
    from app.context_builder import _local_python_neighbors

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "feature.py").write_text("from .helper import work\n", encoding="utf-8")
    (pkg / "helper.py").write_text("def work(): return 1\n", encoding="utf-8")
    assert "pkg/helper.py" in _local_python_neighbors(tmp_path, "pkg/feature.py")


@pytest.mark.asyncio
async def test_watcher_marshals_modified_event_back_to_main_loop(tmp_path, monkeypatch):
    from app.watcher import ProjectChangeHandler

    workspace = tmp_path / "workspace"
    project = workspace / "demo"
    project.mkdir(parents=True)
    changed = project / "main.py"
    changed.write_text("x=1\n", encoding="utf-8")
    monkeypatch.setattr(settings, "WORKSPACE_ROOT", str(workspace))

    handler = ProjectChangeHandler(debounce_seconds=0)
    handler.set_loop(asyncio.get_running_loop())
    seen = []
    handler._debounce_project_update = lambda project_name: seen.append(project_name)
    event = SimpleNamespace(is_directory=False, src_path=str(changed))

    await asyncio.to_thread(handler.on_modified, event)
    await asyncio.sleep(0.02)
    assert seen == ["demo"]


def test_experience_tie_prefers_most_recent(tmp_path, monkeypatch):
    from app.database import init_database, get_db
    from app.experience_memory import record_experience, search_experiences

    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "exp.db"))
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path / "backups"))
    init_database()
    first = record_experience(
        project_name="demo", issue_id="1", task="Fix cache timeout",
        strategy="old", outcome="failed", failure_class="timeout", files=["cache.py"],
    )
    second = record_experience(
        project_name="demo", issue_id="2", task="Fix cache timeout",
        strategy="new", outcome="failed", failure_class="timeout2", files=["cache.py"],
    )
    with get_db() as conn:
        conn.execute("UPDATE engineering_experiences SET last_seen_at=? WHERE id=?", ("2026-01-01T00:00:00+00:00", first["id"]))
        conn.execute("UPDATE engineering_experiences SET last_seen_at=? WHERE id=?", ("2026-09-01T00:00:00+00:00", second["id"]))
        conn.commit()
    found = search_experiences(project_name="demo", task="Fix cache timeout", files=["cache.py"], limit=2)
    assert [x["strategy"] for x in found] == ["new", "old"]


def test_adaptive_router_treats_authentication_bypass_as_security_debug_task():
    from app.adaptive_orchestration import route_task

    route = route_task("Fix authentication bypass in login middleware")
    assert route.task_kind == "security"
    assert route.needs_initial_debugger is True
    assert "security" in route.agent_sequence


def test_experience_memory_concurrent_duplicate_upsert_is_atomic(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from app.database import init_database, get_db
    from app.experience_memory import record_experience

    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "exp-concurrent.db"))
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path / "backups"))
    init_database()

    def write_once(i):
        return record_experience(
            project_name="demo", issue_id=str(i), task="Fix repeated cache timeout",
            strategy="bounded_timeout", outcome="failed", failure_class="timeout",
            files=["cache.py"], lesson=f"attempt {i}",
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(write_once, range(8)))
    assert len({r["id"] for r in results}) == 1
    with get_db() as conn:
        row = conn.execute("SELECT occurrence_count FROM engineering_experiences").fetchone()
    assert row["occurrence_count"] == 8


def test_benchmark_rejects_non_numeric_metrics_as_validation_error(tmp_path, monkeypatch):
    from app.database import init_database
    from app.v11_evaluation import record_benchmark_run

    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "bench.db"))
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path / "backups"))
    init_database()
    with pytest.raises(ValueError, match="llm_calls"):
        record_benchmark_run(
            version="1.1.1", suite_name="bad-input",
            cases=[{"case_id": "x", "passed": True, "llm_calls": {"bad": "value"}}],
        )


@pytest.mark.asyncio
async def test_orchestrator_does_not_write_plan_files_into_live_project(tmp_path, monkeypatch):
    from app import orchestrator
    from app.database import init_database

    workspace = tmp_path / "workspace"
    project = workspace / "demo"
    project.mkdir(parents=True)
    (project / "names.py").write_text("def name(x): return x\n", encoding="utf-8")
    monkeypatch.setattr(settings, "WORKSPACE_ROOT", str(workspace))
    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "orchestrator.db"))
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path / "backups"))
    init_database()

    async def fake_repair(issue):
        return {"status": "verified", "attempts": [], "quality": {"accepted": True, "score": 1.0}, "proposed_changes": []}

    monkeypatch.setattr(orchestrator, "repair_issue", fake_repair)
    result = await orchestrator.run_orchestrator(
        "Add a small name formatter", ["names.py"], project_name="demo", auto_apply=False
    )
    assert result["status"] == "waiting_approval"
    assert not (project / "raw_prompt.md").exists()
    assert not (project / "plan.md").exists()
