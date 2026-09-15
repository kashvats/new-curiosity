import json
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.database import get_db, init_database


def _workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    project = workspace / "demo"
    project.mkdir(parents=True)
    (project / "README.md").write_text("# Demo\n", encoding="utf-8")
    monkeypatch.setattr(settings, "WORKSPACE_ROOT", str(workspace))
    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "part7.db"))
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(settings, "IMPROVEMENT_POLICY_SIGNING_KEY", "")
    monkeypatch.setattr(settings, "IMPROVEMENT_APPROVER_CREDENTIALS_JSON", "{}")
    init_database()
    return workspace, project


def _snapshot(project, score=95.0):
    return {
        "project_name": "demo", "project_root": str(project), "health_score": score,
        "dimensions": {"tests": 95, "security": 100, "architecture": 95, "quality": 95, "knowledge": 95, "dependencies": 100, "drift": 100},
        "findings": [], "checks": {"passed": True, "checks": []}, "metadata": {},
    }


def test_part7_schema_adds_integrity_approval_coverage_and_regression_state(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    with get_db() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        cycles = {row[1] for row in conn.execute("PRAGMA table_info(improvement_cycles)").fetchall()}
        candidates = {row[1] for row in conn.execute("PRAGMA table_info(improvement_candidates)").fetchall()}
    assert {"improvement_approvals", "improvement_coverage_reports", "improvement_regression_attributions"}.issubset(tables)
    assert "policy_integrity_json" in cycles
    assert {"base_risk", "cooldown_until", "cooldown_reason", "risk_escalation_json"}.issubset(candidates)


def test_cycle_policy_snapshot_is_sealed_and_tampering_is_detected(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "IMPROVEMENT_POLICY_SIGNING_KEY", "part7-signing-secret")
    from app.improvement_integrity import verify_policy_snapshot
    from app.improvement_store import create_improvement_cycle, get_improvement_cycle

    cycle = create_improvement_cycle(project_name="demo", trigger="manual", policy="manual", request={})
    assert cycle["policy_integrity"]["signed"] is True
    assert verify_policy_snapshot(cycle["policy_snapshot"], cycle["policy_integrity"])["passed"] is True

    with get_db() as conn:
        snapshot = dict(cycle["policy_snapshot"])
        snapshot["policy"]["min_priority"] = 999
        conn.execute("UPDATE improvement_cycles SET policy_snapshot_json=? WHERE id=?", (json.dumps(snapshot), cycle["id"]))
        conn.commit()
    tampered = get_improvement_cycle(cycle["id"])
    result = verify_policy_snapshot(tampered["policy_snapshot"], tampered["policy_integrity"])
    assert result["passed"] is False
    assert result["reason"] in {"policy_snapshot_digest_mismatch", "policy_snapshot_signature_mismatch"}


def test_authenticated_role_approval_is_recorded_without_storing_token(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "IMPROVEMENT_APPROVER_CREDENTIALS_JSON", json.dumps({"alice": {"role": "maintainer", "token": "secret-token"}}))
    from app.improvement_approvals import approval_requirement_status, record_cycle_approval
    from app.improvement_policy import save_improvement_policy
    from app.improvement_store import create_improvement_cycle

    policy = save_improvement_policy("demo", {"approval": {"min_verified_approvals": 1, "required_roles": ["maintainer"]}})
    cycle = create_improvement_cycle(project_name="demo", trigger="manual", policy="manual", request={})
    before = approval_requirement_status(cycle["id"], policy["policy"])
    assert before["passed"] is False
    approval = record_cycle_approval(cycle_id=cycle["id"], project_name="demo", approver_id="alice", role="maintainer", token="secret-token")
    assert approval["verified"] is True
    assert approval_requirement_status(cycle["id"], policy["policy"])["passed"] is True
    with get_db() as conn:
        row = conn.execute("SELECT * FROM improvement_approvals WHERE id=?", (approval["id"],)).fetchone()
    assert "secret-token" not in json.dumps(dict(row))


def test_coverage_json_and_cobertura_ingestion_produces_delta(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app.improvement_coverage import coverage_delta, store_coverage_report

    store_coverage_report(project_name="demo", cycle_id="c1", phase="baseline", report={"totals": {"percent_covered": 72.5}}, report_format="json")
    store_coverage_report(project_name="demo", cycle_id="c1", phase="post_apply", report='<coverage line-rate="0.81" branch-rate="0.63" lines-valid="100" lines-covered="81" />', report_format="cobertura")
    delta = coverage_delta("demo", cycle_id="c1")
    assert delta["comparable"] is True
    assert delta["line_delta"] == 8.5
    assert delta["current"]["branch_coverage"] == 63.0


def test_recent_failure_places_matching_candidate_on_cooldown_and_escalates_risk(tmp_path, monkeypatch):
    _, project = _workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "IMPROVEMENT_COOLDOWN_VALIDATION_HOURS", 24)
    monkeypatch.setattr(settings, "IMPROVEMENT_RISK_ESCALATION_FAILURES", 1)
    from app.candidate_suppression import apply_repeat_suppression
    from app.improvement_brain import generate_improvement_candidates
    from app.improvement_risk_controls import apply_failure_cooldowns_and_risk
    from app.improvement_store import create_improvement_cycle, store_improvement_candidates, update_improvement_candidate

    snap = _snapshot(project, 70)
    snap["findings"] = [{
        "category": "quality", "severity": "medium", "code": "todo_markers", "message": "TODO",
        "likely_files": ["a.py"], "suggested_task": "Clean TODO safely", "risk": "low", "benefit": .7,
        "confidence": .9, "urgency": .8, "estimated_cost": .5, "validation_plan": [],
    }]
    cycle = create_improvement_cycle(project_name="demo", trigger="manual", policy="manual", request={})
    old = apply_repeat_suppression("demo", [generate_improvement_candidates(snap, cycle_id=cycle["id"])[0]], repeat_limit=5)[0]
    saved = store_improvement_candidates(cycle["id"], [old])[0]
    update_improvement_candidate(saved["id"], status="validation_failed")

    fresh = apply_repeat_suppression("demo", [generate_improvement_candidates(snap, cycle_id="fresh")[0]], repeat_limit=5)[0]
    controlled = apply_failure_cooldowns_and_risk("demo", [fresh])[0]
    assert controlled["cooldown_until"]
    assert controlled["cooldown_reason"] == "failure_class:validation_failure"
    assert controlled["base_risk"] == "low"
    assert controlled["risk"] == "medium"


def test_regression_attribution_records_dimension_deltas(tmp_path, monkeypatch):
    _, project = _workspace(tmp_path, monkeypatch)
    from app.improvement_regression_attribution import list_regression_attributions, store_regression_attribution

    before = _snapshot(project, 90)
    after = _snapshot(project, 85)
    after["dimensions"]["tests"] = 80
    record = store_regression_attribution(
        cycle_id="cycle", project_name="demo", candidate_id="candidate", issue_id="issue", outcome_id="outcome",
        baseline=before, final=after, changed_files=["a.py"], apply_status="applied",
    )
    assert record["regressed_dimensions"]["tests"] == -15.0
    assert record["failure_class"] == "dimension_regression"
    assert list_regression_attributions("demo")[0]["confidence"] == "high"


def test_readiness_is_not_safe_without_evidence_and_can_become_safe(tmp_path, monkeypatch):
    _, project = _workspace(tmp_path, monkeypatch)
    from app.autonomy_readiness import autonomy_readiness_report
    from app.improvement_coverage import store_coverage_report
    from app.improvement_policy import save_improvement_policy
    from app.improvement_store import store_health_snapshot, store_improvement_outcome
    from app.project_baselines import create_project_baseline

    first = autonomy_readiness_report("demo")
    assert first["verdict"] == "not_safe_to_automate"
    assert first["scheduler_enabled"] is False

    monkeypatch.setattr(settings, "IMPROVEMENT_POLICY_SIGNING_KEY", "sign-me")
    monkeypatch.setattr(settings, "IMPROVEMENT_APPROVER_CREDENTIALS_JSON", json.dumps({"alice": {"role": "maintainer", "token": "secret"}}))
    save_improvement_policy("demo", {"approval": {"min_verified_approvals": 1, "required_roles": ["maintainer"]}})
    create_project_baseline("demo", label="approved")
    store_health_snapshot(project_name="demo", snapshot=_snapshot(project, 95), cycle_id=None, phase="manual")
    store_coverage_report(project_name="demo", phase="current", report={"totals": {"percent_covered": 90}}, report_format="json")
    for idx in range(int(settings.IMPROVEMENT_READINESS_MIN_SUCCESSFUL_CYCLES)):
        store_improvement_outcome(
            cycle_id=f"cycle-{idx}", candidate_id=None, issue_id=None, project_name="demo", apply_status="applied",
            baseline_score=90, final_score=92, baseline_snapshot_id=None, final_snapshot_id=None, details={},
        )
    ready = autonomy_readiness_report("demo")
    assert ready["verdict"] == "safe_to_automate"
    assert ready["eligible"] is True
    assert ready["automatic_source_apply_enabled"] is False


def test_controller_blocks_tampered_policy_before_apply(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app import improvement_controller as controller
    from app.improvement_store import create_improvement_cycle, get_improvement_cycle, update_improvement_cycle

    cycle = create_improvement_cycle(project_name="demo", trigger="manual", policy="manual", request={})
    update_improvement_cycle(cycle["id"], state="WAITING_APPROVAL", selected_issue_id="issue-x")
    with get_db() as conn:
        bad = dict(cycle["policy_snapshot"])
        bad["version"] = 999
        conn.execute("UPDATE improvement_cycles SET policy_snapshot_json=? WHERE id=?", (json.dumps(bad), cycle["id"]))
        conn.commit()
    result = controller.apply_improvement_cycle(cycle["id"], confirm=True)
    assert result["state"] == "POLICY_INTEGRITY_BLOCKED"


def test_part7_routes_registered():
    from app.main import app
    paths = {route.path for route in app.routes}
    required = {
        "/improvements/readiness", "/improvements/coverage/reports", "/improvements/coverage/delta",
        "/improvements/regressions", "/improvements/cycles/{cycle_id}/approve",
        "/improvements/cycles/{cycle_id}/approvals",
    }
    assert required.issubset(paths)
