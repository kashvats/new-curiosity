import asyncio
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.database import get_db, init_database


def _workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    project = workspace / "demo"
    project.mkdir(parents=True)
    (project / "README.md").write_text("# Demo\n", encoding="utf-8")
    monkeypatch.setattr(settings, "WORKSPACE_ROOT", str(workspace))
    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "part8.db"))
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(settings, "IMPROVEMENT_DRY_RUN_SCHEDULER_ENABLED", False)
    monkeypatch.setattr(settings, "IMPROVEMENT_POLICY_SIGNING_KEY", "")
    monkeypatch.setattr(settings, "IMPROVEMENT_APPROVER_CREDENTIALS_JSON", "{}")
    monkeypatch.setattr(settings, "IMPROVEMENT_SCHEDULER_MAX_GLOBAL_RUNS_PER_HOUR", 10)
    monkeypatch.setattr(settings, "IMPROVEMENT_SCHEDULER_MAX_PROJECT_RUNS_PER_DAY", 4)
    monkeypatch.setattr(settings, "IMPROVEMENT_SCHEDULER_MIN_INTERVAL_MINUTES", 1)
    monkeypatch.setattr(settings, "IMPROVEMENT_EVIDENCE_WEBHOOK_TOKEN", "")
    init_database()
    return workspace, project


def test_part8_schema_adds_scheduler_control_plane_tables(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    expected = {
        "improvement_schedules",
        "improvement_scheduler_runs",
        "improvement_scheduler_leases",
        "improvement_scheduler_control",
        "improvement_ci_evidence",
        "improvement_slo_evidence",
    }
    with get_db() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert expected.issubset(tables)


def test_maintenance_window_gate_is_timezone_aware(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app.improvement_scheduler_guards import maintenance_window_status

    schedule = {
        "timezone": "UTC",
        "maintenance_windows": [{"days": ["mon"], "start": "09:00", "end": "11:00"}],
    }
    inside = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)  # Monday
    outside = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    assert maintenance_window_status(schedule, now=inside)["passed"] is True
    assert maintenance_window_status(schedule, now=outside)["passed"] is False


def test_scheduler_lease_excludes_other_owner_and_can_be_released(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app.improvement_scheduler_store import acquire_lease, release_lease

    first = acquire_lease("scheduler:project:demo", owner_id="a", ttl_seconds=60)
    second = acquire_lease("scheduler:project:demo", owner_id="b", ttl_seconds=60)
    assert first["acquired"] is True
    assert second["acquired"] is False
    assert release_lease("scheduler:project:demo", owner_id="a") is True
    third = acquire_lease("scheduler:project:demo", owner_id="b", ttl_seconds=60)
    assert third["acquired"] is True


def test_kill_switch_blocks_scheduler_guards(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app.improvement_scheduler_guards import evaluate_schedule_guards
    from app.improvement_scheduler_store import create_schedule, set_scheduler_kill_switch

    schedule = create_schedule(
        project_name="demo", name="nightly", interval_minutes=60,
        require_readiness=False, require_ci_success=False, require_slo=False,
    )
    set_scheduler_kill_switch(enabled=True, reason="incident", scope="global")
    result = evaluate_schedule_guards(schedule, include_readiness=False)
    assert result["passed"] is False
    assert any(g["name"] == "emergency_kill_switch" and not g["passed"] for g in result["gates"])


def test_ci_and_slo_evidence_gate_scheduled_execution(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "IMPROVEMENT_SCHEDULER_CI_MAX_AGE_MINUTES", 120)
    monkeypatch.setattr(settings, "IMPROVEMENT_SCHEDULER_SLO_MAX_AGE_MINUTES", 120)
    monkeypatch.setattr(settings, "IMPROVEMENT_EVIDENCE_WEBHOOK_TOKEN", "evidence-secret")
    from app.improvement_scheduler_guards import evaluate_schedule_guards
    from app.improvement_scheduler_store import create_schedule, store_ci_evidence, store_slo_evidence

    schedule = create_schedule(
        project_name="demo", name="guarded", interval_minutes=60,
        require_readiness=False, require_ci_success=True, require_slo=True,
    )
    blocked = evaluate_schedule_guards(schedule, include_readiness=False)
    assert blocked["passed"] is False

    store_ci_evidence(project_name="demo", provider="github", status="success")
    store_slo_evidence(
        project_name="demo", source="prometheus", availability=99.95, error_rate=0.2,
        latency_p95_ms=300, error_budget_remaining=80,
    )
    allowed = evaluate_schedule_guards(schedule, include_readiness=False)
    assert allowed["passed"] is True


def test_observe_propose_schedule_is_forced_to_observe_only(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app import improvement_scheduler as scheduler
    from app.improvement_scheduler_store import create_schedule
    from app.improvement_store import get_improvement_cycle

    captured = {}

    async def fake_run(cycle_id):
        cycle = get_improvement_cycle(cycle_id)
        captured.update(cycle)
        return cycle

    monkeypatch.setattr(scheduler, "run_improvement_cycle", fake_run)
    schedule = create_schedule(
        project_name="demo", name="dry-run", interval_minutes=60, require_readiness=False,
        request={"policy": "manual", "experiment_mode": True, "pause_for_candidate_selection": True, "run_checks": False},
    )
    result = asyncio.run(scheduler.run_schedule(schedule["id"], ignore_due=True))
    assert result["status"] == "completed"
    assert captured["policy"] == "observe_only"
    assert captured["request"]["policy"] == "observe_only"
    assert captured["request"]["experiment_mode"] is False
    assert captured["request"]["pause_for_candidate_selection"] is False
    assert result["decision"]["scheduled_source_apply_enabled"] is False


def test_canary_schedule_captures_health_without_creating_cycle(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app import improvement_scheduler as scheduler
    from app.improvement_scheduler_store import create_schedule, list_scheduler_runs
    from app.improvement_store import list_improvement_cycles

    monkeypatch.setattr(scheduler, "capture_project_health", lambda project_name, run_checks=False: {
        "project_name": project_name,
        "health_score": 95.0,
        "dimensions": {"tests": 95.0},
        "findings": [],
        "checks": {},
        "metadata": {},
    })
    schedule = create_schedule(
        project_name="demo", name="canary", interval_minutes=60, mode="canary_observe", require_readiness=False,
    )
    result = asyncio.run(scheduler.run_schedule(schedule["id"], ignore_due=True))
    assert result["status"] == "canary_passed"
    assert list_improvement_cycles(project_name="demo") == []
    runs = list_scheduler_runs(project_name="demo")
    assert runs[0]["cycle_id"] is None
    assert runs[0]["decision"]["canary"]["passed"] is True


def test_scheduler_rate_limit_blocks_second_run(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "IMPROVEMENT_SCHEDULER_MAX_GLOBAL_RUNS_PER_HOUR", 1)
    monkeypatch.setattr(settings, "IMPROVEMENT_SCHEDULER_MAX_PROJECT_RUNS_PER_DAY", 10)
    from app import improvement_scheduler as scheduler
    from app.improvement_scheduler_store import create_schedule
    from app.improvement_store import get_improvement_cycle

    async def fake_run(cycle_id):
        return get_improvement_cycle(cycle_id)

    monkeypatch.setattr(scheduler, "run_improvement_cycle", fake_run)
    schedule = create_schedule(project_name="demo", name="limited", interval_minutes=60, require_readiness=False, max_runs_per_day=10)
    first = asyncio.run(scheduler.run_schedule(schedule["id"], ignore_due=True))
    second = asyncio.run(scheduler.run_schedule(schedule["id"], ignore_due=True))
    assert first["status"] == "completed"
    assert second["status"] == "blocked"
    assert any(g["name"] == "rate_limits" for g in second["decision"]["blockers"])


def test_evidence_webhook_token_is_enforced_when_configured(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "IMPROVEMENT_EVIDENCE_WEBHOOK_TOKEN", "webhook-secret")
    from fastapi import HTTPException
    from app.improvement_scheduler_api import _require_evidence_auth

    try:
        _require_evidence_auth("wrong")
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 401
    _require_evidence_auth("webhook-secret")



def test_emergency_stop_requests_cancel_for_linked_active_dry_run(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app.improvement_scheduler_api import KillSwitchRequest, scheduler_kill_switch
    from app.improvement_scheduler_store import attach_scheduler_cycle, create_scheduler_run
    from app.improvement_store import create_improvement_cycle, get_improvement_cycle

    cycle = create_improvement_cycle(project_name="demo", trigger="scheduler:test", policy="observe_only", request={})
    run = create_scheduler_run(schedule_id="schedule-x", project_name="demo", mode="observe_propose")
    attach_scheduler_cycle(run["id"], cycle["id"])
    result = scheduler_kill_switch(KillSwitchRequest(enabled=True, reason="incident", scope="global", confirm=True))
    assert cycle["id"] in result["cancel_requested_cycle_ids"]
    assert get_improvement_cycle(cycle["id"])["cancel_requested"] is True

def test_part8_routes_registered_and_source_apply_remains_disabled(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app.improvement_scheduler import scheduler_status
    from app.main import app

    paths = {route.path for route in app.routes}
    required = {
        "/improvements/scheduler/status",
        "/improvements/scheduler/schedules",
        "/improvements/scheduler/tick",
        "/improvements/scheduler/kill-switch",
        "/improvements/scheduler/schedules/{schedule_id}/run-now",
        "/improvements/evidence/ci",
        "/improvements/evidence/slo",
    }
    assert required.issubset(paths)
    status = scheduler_status()
    assert status["automatic_source_apply_enabled"] is False
    assert status["scheduled_source_apply_enabled"] is False
