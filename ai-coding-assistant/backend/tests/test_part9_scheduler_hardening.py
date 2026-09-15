import asyncio
import json
from datetime import datetime, timezone

import pytest

from app.config import settings
from app.database import get_db, init_database


def _workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    project = workspace / "demo"
    project.mkdir(parents=True)
    (project / "README.md").write_text("# Demo\n", encoding="utf-8")
    monkeypatch.setattr(settings, "WORKSPACE_ROOT", str(workspace))
    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "part9.db"))
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(settings, "IMPROVEMENT_DRY_RUN_SCHEDULER_ENABLED", False)
    monkeypatch.setattr(settings, "IMPROVEMENT_POLICY_SIGNING_KEY", "")
    monkeypatch.setattr(settings, "IMPROVEMENT_APPROVER_CREDENTIALS_JSON", "{}")
    monkeypatch.setattr(settings, "IMPROVEMENT_OPERATOR_CREDENTIALS_JSON", "{}")
    monkeypatch.setattr(settings, "IMPROVEMENT_EVIDENCE_WEBHOOK_TOKEN", "")
    monkeypatch.setattr(settings, "IMPROVEMENT_EVIDENCE_WEBHOOK_SIGNING_SECRET", "")
    monkeypatch.setattr(settings, "IMPROVEMENT_SCHEDULER_MIN_INTERVAL_MINUTES", 1)
    monkeypatch.setattr(settings, "IMPROVEMENT_SCHEDULER_STAGING_MIN_INTERVAL_MINUTES", 2)
    monkeypatch.setattr(settings, "IMPROVEMENT_SCHEDULER_PROD_MIN_INTERVAL_MINUTES", 3)
    monkeypatch.setattr(settings, "IMPROVEMENT_SCHEDULER_MAX_GLOBAL_RUNS_PER_HOUR", 50)
    monkeypatch.setattr(settings, "IMPROVEMENT_SCHEDULER_MAX_PROJECT_RUNS_PER_DAY", 50)
    init_database()
    return workspace, project


def test_part9_schema_adds_hardening_tables_and_columns(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    expected = {
        "improvement_webhook_deliveries",
        "improvement_operator_audit",
        "improvement_scheduler_alerts",
        "improvement_scheduler_telemetry",
        "improvement_scheduler_lease_fences",
    }
    with get_db() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        schedule_cols = {row[1] for row in conn.execute("PRAGMA table_info(improvement_schedules)").fetchall()}
        lease_cols = {row[1] for row in conn.execute("PRAGMA table_info(improvement_scheduler_leases)").fetchall()}
    assert expected.issubset(tables)
    assert {"environment", "ci_branch", "ci_commit_sha", "bind_ci_to_project_head"}.issubset(schedule_cols)
    assert "fence_token" in lease_cols


def test_signed_webhook_rejects_replay(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "IMPROVEMENT_EVIDENCE_WEBHOOK_SIGNING_SECRET", "signing-secret")
    from app.improvement_scheduler_security import build_evidence_signature, verify_and_record_evidence_delivery

    payload = {"project_name": "demo", "status": "success"}
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    delivery_id = "delivery-1"
    signature = build_evidence_signature(payload=payload, timestamp=timestamp, delivery_id=delivery_id)
    verified = verify_and_record_evidence_delivery(
        project_name="demo", evidence_type="ci", payload=payload, signature=signature,
        timestamp=timestamp, delivery_id=delivery_id,
    )
    assert verified["authenticated"] is True
    with pytest.raises(ValueError, match="already been processed"):
        verify_and_record_evidence_delivery(
            project_name="demo", evidence_type="ci", payload=payload, signature=signature,
            timestamp=timestamp, delivery_id=delivery_id,
        )


def test_signed_webhook_rejects_stale_timestamp(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "IMPROVEMENT_EVIDENCE_WEBHOOK_SIGNING_SECRET", "signing-secret")
    monkeypatch.setattr(settings, "IMPROVEMENT_EVIDENCE_WEBHOOK_MAX_SKEW_SECONDS", 30)
    from app.improvement_scheduler_security import build_evidence_signature, verify_and_record_evidence_delivery

    payload = {"project_name": "demo", "status": "success"}
    timestamp = "1"
    signature = build_evidence_signature(payload=payload, timestamp=timestamp, delivery_id="old")
    with pytest.raises(ValueError, match="outside the allowed replay window"):
        verify_and_record_evidence_delivery(
            project_name="demo", evidence_type="ci", payload=payload, signature=signature,
            timestamp=timestamp, delivery_id="old",
        )


def test_operator_identity_is_verified_and_audited(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "IMPROVEMENT_OPERATOR_CREDENTIALS_JSON", json.dumps({"ops1": {"role": "release-manager", "token": "secret"}}))
    from app.improvement_scheduler_security import list_operator_audit, record_operator_audit, verify_operator

    operator = verify_operator("ops1", "secret")
    assert operator["verified"] is True
    assert operator["role"] == "release-manager"
    with pytest.raises(ValueError):
        verify_operator("ops1", "wrong")
    record_operator_audit(operator=operator, action="schedule.create", project_name="demo", metadata={"x": 1})
    events = list_operator_audit(project_name="demo")
    assert events[0]["operator_id"] == "ops1"
    assert events[0]["action"] == "schedule.create"


def test_ci_branch_and_commit_binding_selects_matching_evidence(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app.improvement_scheduler_guards import ci_evidence_status
    from app.improvement_scheduler_store import create_schedule, store_ci_evidence

    schedule = create_schedule(
        project_name="demo", name="bound", interval_minutes=10, require_readiness=False,
        require_ci_success=True, ci_branch="main", ci_commit_sha="abc123",
    )
    store_ci_evidence(project_name="demo", provider="github", status="success", branch="dev", commit_sha="abc123")
    blocked = ci_evidence_status(schedule)
    assert blocked["passed"] is False
    store_ci_evidence(project_name="demo", provider="github", status="success", branch="main", commit_sha="abc123")
    allowed = ci_evidence_status(schedule)
    assert allowed["passed"] is True
    assert allowed["evidence"]["binding"]["expected_branch"] == "main"


def test_prod_environment_policy_requires_strong_controls(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app.improvement_scheduler_environment import environment_policy_status

    schedule = {
        "project_name": "demo", "environment": "prod", "interval_minutes": 3,
        "require_readiness": False, "require_ci_success": False, "require_slo": False,
        "ci_branch": None, "ci_commit_sha": None, "bind_ci_to_project_head": False,
    }
    blocked = environment_policy_status(schedule)
    assert blocked["passed"] is False
    failures = set(blocked["evidence"]["failures"])
    assert "require_readiness" in failures
    assert "signed_webhook_not_configured" in failures
    assert "operator_registry_not_configured" in failures

    monkeypatch.setattr(settings, "IMPROVEMENT_EVIDENCE_WEBHOOK_SIGNING_SECRET", "signed")
    monkeypatch.setattr(settings, "IMPROVEMENT_OPERATOR_CREDENTIALS_JSON", json.dumps({"ops": {"role": "operator", "token": "t"}}))
    schedule.update({"require_readiness": True, "require_ci_success": True, "require_slo": True, "ci_branch": "main"})
    assert environment_policy_status(schedule)["passed"] is True


def test_fenced_leases_are_monotonic_and_stale_token_cannot_release(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app.improvement_scheduler_store import acquire_lease, release_lease, validate_lease

    first = acquire_lease("scheduler:project:demo", owner_id="worker-a", ttl_seconds=60)
    assert first["fence_token"] == 1
    assert validate_lease("scheduler:project:demo", owner_id="worker-a", fence_token=1)
    assert release_lease("scheduler:project:demo", owner_id="worker-a", fence_token=1)
    second = acquire_lease("scheduler:project:demo", owner_id="worker-b", ttl_seconds=60)
    assert second["fence_token"] == 2
    assert release_lease("scheduler:project:demo", owner_id="worker-a", fence_token=1) is False
    assert validate_lease("scheduler:project:demo", owner_id="worker-b", fence_token=2)


def test_schedule_simulation_has_no_run_or_cycle_side_effects(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app.improvement_scheduler import simulate_schedule
    from app.improvement_scheduler_store import create_schedule, list_scheduler_runs
    from app.improvement_store import list_improvement_cycles

    schedule = create_schedule(project_name="demo", name="preview", interval_minutes=10, require_readiness=False)
    result = simulate_schedule(schedule, include_readiness=False)
    assert result["simulation"] is True
    assert list_scheduler_runs(project_name="demo") == []
    assert list_improvement_cycles(project_name="demo") == []
    assert result["automatic_source_apply_enabled"] is False


def test_blocked_scheduler_run_creates_alert_and_metrics(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app import improvement_scheduler as scheduler
    from app.improvement_scheduler_observability import list_scheduler_alerts, prometheus_metrics, scheduler_metrics_snapshot
    from app.improvement_scheduler_store import create_schedule, set_scheduler_kill_switch

    schedule = create_schedule(project_name="demo", name="blocked", interval_minutes=10, require_readiness=False)
    set_scheduler_kill_switch(enabled=True, reason="incident", scope="global")
    result = asyncio.run(scheduler.run_schedule(schedule["id"], ignore_due=True))
    assert result["status"] == "blocked"
    alerts = list_scheduler_alerts(project_name="demo")
    assert alerts and alerts[0]["code"] == "scheduler_blocked"
    metrics = scheduler_metrics_snapshot("demo")
    assert metrics["open_alerts"] >= 1
    assert metrics["runs_by_status"]["blocked"] >= 1
    text = prometheus_metrics("demo")
    assert "ai_coding_assistant_scheduler_open_alerts" in text
    assert "automatic" not in text.lower() or "disabled" in text.lower()


def test_part9_routes_and_capabilities_are_registered(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app.improvement_scheduler import scheduler_status
    from app.main import app

    paths = {route.path for route in app.routes}
    required = {
        "/improvements/scheduler/simulate",
        "/improvements/scheduler/schedules/{schedule_id}/simulate",
        "/improvements/scheduler/metrics",
        "/improvements/scheduler/metrics/prometheus",
        "/improvements/scheduler/telemetry",
        "/improvements/scheduler/alerts",
        "/improvements/scheduler/alerts/{alert_id}/ack",
        "/improvements/scheduler/audit",
    }
    assert required.issubset(paths)
    status = scheduler_status()
    assert status["part9_production_hardening"] is True
    assert status["lease_fencing_enabled"] is True
    assert status["automatic_source_apply_enabled"] is False
    assert status["scheduled_source_apply_enabled"] is False
