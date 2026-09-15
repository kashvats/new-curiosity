import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.config import settings
from app.database import get_db, init_database


def _workspace(tmp_path, monkeypatch):
    workspace=tmp_path/"workspace"; project=workspace/"demo"; project.mkdir(parents=True)
    (project/"app.py").write_text("VALUE = 1\n",encoding="utf-8")
    (project/"requirements.txt").write_text("fastapi==0.109.0\n",encoding="utf-8")
    (project/"package.json").write_text('{"dependencies":{"react":"18.3.1"}}',encoding="utf-8")
    monkeypatch.setattr(settings,"WORKSPACE_ROOT",str(workspace))
    monkeypatch.setattr(settings,"DATABASE_PATH",str(tmp_path/"part14.db"))
    monkeypatch.setattr(settings,"BACKUP_DIR",str(tmp_path/"backups"))
    monkeypatch.setattr(settings,"IMPROVEMENT_RELEASE_ROOT",str(tmp_path/"releases"))
    monkeypatch.setattr(settings,"IMPROVEMENT_RELEASE_BUILD_MODE","validate_only")
    monkeypatch.setattr(settings,"IMPROVEMENT_RELEASE_REQUIRE_CONTAINER_BUILD",False)
    monkeypatch.setattr(settings,"IMPROVEMENT_RELEASE_REQUIRE_VULNERABILITY_REPORT",True)
    monkeypatch.setattr(settings,"IMPROVEMENT_RELEASE_REQUIRE_SIGNATURE",True)
    monkeypatch.setattr(settings,"IMPROVEMENT_RELEASE_SIGNING_KEY","release-test-key")
    monkeypatch.setattr(settings,"IMPROVEMENT_RELEASE_PREVIEW_PROVIDER","none")
    monkeypatch.setattr(settings,"IMPROVEMENT_STAGING_EXECUTION_ENABLED",False)
    monkeypatch.setattr(settings,"IMPROVEMENT_OPERATOR_CREDENTIALS_JSON",json.dumps({
        "rel":{"role":"release-manager","token":"rel-secret"},
        "ops":{"role":"ops","token":"ops-secret"},
        "sec":{"role":"security","token":"sec-secret"},
        "maint":{"role":"maintainer","token":"maint-secret"},
        "dev":{"role":"developer","token":"dev-secret"},
    }))
    monkeypatch.setattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_MIN_APPROVALS",2)
    monkeypatch.setattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_REQUIRED_ROLES","release-manager,ops")
    monkeypatch.setattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_ALLOWED_APPROVER_ROLES","release-manager,ops,security,maintainer")
    monkeypatch.setattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_CHANGE_TICKET_REQUIRED",True)
    monkeypatch.setattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_CHANGE_TICKET_PATTERN",r"^[A-Z][A-Z0-9]+-[0-9]+$")
    monkeypatch.setattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_FREEZE_WINDOWS_JSON","[]")
    monkeypatch.setattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_RELEASE_TRAIN_REQUIRED",False)
    monkeypatch.setattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_RELEASE_TRAIN_WINDOW_REQUIRED",False)
    init_database(); return workspace,project


def _verified_issue(project: Path, issue_id="issue-14"):
    from app.verified_candidate_store import store_verified_repair
    old=(project/"app.py").read_text(encoding="utf-8")
    return store_verified_repair(issue_id=issue_id,project_name="demo",task="change value",
        proposed_changes=[{"action":"modify","path":"app.py","content":"VALUE = 2\n","expected_sha256":hashlib.sha256(old.encode()).hexdigest()}],
        validation={"passed":True,"checks":[{"args":["python","-m","compileall","-q","."],"passed":True,"purpose":"compile"}]},
        review={"passed":True},security={"passed":True},quality={"passed":True})


def _production_request(project: Path):
    # Seed the already-tested Part 13 handoff boundary directly. Part 14 tests should
    # exercise governance, not repeatedly rebuild/stage the same candidate.
    from app.improvement_release_store import create_release_candidate, update_release_candidate
    from app.improvement_release_security import sign_digest
    from app.improvement_staging_store import create_production_release_request
    release=create_release_candidate(project_name="demo",issue_id="issue-14",commit_sha="abc1234",scm_provider="github",scm_target="org/repo")
    release=update_release_candidate(release["id"],status="staging_validated",evidence_bundle={"staging_validated":True})
    evidence_digest=hashlib.sha256(f"release:{release['id']}:validated".encode()).hexdigest()
    signature=sign_digest(evidence_digest,context=f"release:{release['id']}:production-release-request")
    request=create_production_release_request(release_id=release["id"],requested_by="rel",role="release-manager",evidence_digest=evidence_digest,
        request={"notes":"ready","production_deployment_executed":False,"human_authorized_handoff":True,"evidence_signature":signature})
    return release,request


def _case_ready(tmp_path,monkeypatch):
    _,project=_workspace(tmp_path,monkeypatch); _,request=_production_request(project)
    from app.improvement_production_governance import create_case_from_request, attach_change_ticket, generate_rollout_plan
    case=create_case_from_request(request["id"],operator={"verified":True,"operator_id":"rel","role":"release-manager"})
    attach_change_ticket(case["id"],system="jira",reference="REL-140",url="https://jira.example/REL-140",operator={"verified":True,"operator_id":"rel","role":"release-manager"})
    generate_rollout_plan(case["id"],strategy="canary",operator={"verified":True,"operator_id":"rel","role":"release-manager"})
    return case


def test_part14_schema_and_capabilities(tmp_path,monkeypatch):
    _workspace(tmp_path,monkeypatch)
    from app.improvement_production_governance import production_governance_capabilities
    with get_db() as conn:
        tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"improvement_production_governance_cases","improvement_production_governance_approvals","improvement_release_trains","improvement_production_deployment_packages","improvement_production_governance_events"}.issubset(tables)
    caps=production_governance_capabilities()
    assert caps["multi_person_approval"] is True
    assert caps["production_credentials_stored"] is False
    assert caps["production_deployment_supported"] is False


def test_case_requires_verified_creator_and_valid_signed_request(tmp_path,monkeypatch):
    _,project=_workspace(tmp_path,monkeypatch); _,request=_production_request(project)
    from app.improvement_production_governance import create_case_from_request
    with pytest.raises(ValueError):
        create_case_from_request(request["id"],operator={"verified":False,"operator_id":"anon","role":"local"})
    case=create_case_from_request(request["id"],operator={"verified":True,"operator_id":"rel","role":"release-manager"})
    assert case["production_request_id"] == request["id"]
    with get_db() as conn:
        conn.execute("UPDATE improvement_production_release_requests SET evidence_digest='tampered' WHERE id=?",(request["id"],)); conn.commit()
    # Existing case can be inspected, but a fresh request integrity check must fail on creation after direct tampering.
    with get_db() as conn:
        conn.execute("DELETE FROM improvement_production_governance_cases WHERE id=?",(case["id"],)); conn.commit()
    with pytest.raises(ValueError):
        create_case_from_request(request["id"],operator={"verified":True,"operator_id":"rel","role":"release-manager"})


def test_change_ticket_rollout_and_evidence_bound_quorum(tmp_path,monkeypatch):
    case=_case_ready(tmp_path,monkeypatch)
    from app.improvement_production_governance import submit_approval, evaluate_case, generate_rollout_plan
    submit_approval(case["id"],operator={"verified":True,"operator_id":"rel","role":"release-manager"})
    submit_approval(case["id"],operator={"verified":True,"operator_id":"ops","role":"ops"})
    ready=evaluate_case(case["id"])
    assert ready["ready_to_lock"] is True
    assert ready["approval_summary"]["distinct_approvers"] == 2
    generate_rollout_plan(case["id"],strategy="blue_green",operator={"verified":True,"operator_id":"rel","role":"release-manager"})
    stale=evaluate_case(case["id"])
    assert stale["ready_to_lock"] is False
    assert "approval_quorum_not_met" in stale["blockers"]
    assert stale["approval_summary"]["stale_approvals"] == 2


def test_duplicate_approval_same_operator_and_evidence_is_rejected(tmp_path,monkeypatch):
    case=_case_ready(tmp_path,monkeypatch)
    from app.improvement_production_governance import submit_approval
    operator={"verified":True,"operator_id":"rel","role":"release-manager"}
    submit_approval(case["id"],operator=operator)
    with pytest.raises(ValueError): submit_approval(case["id"],operator=operator)


def test_freeze_window_blocks_lock_readiness(tmp_path,monkeypatch):
    case=_case_ready(tmp_path,monkeypatch)
    from app.improvement_production_governance import submit_approval, evaluate_case
    submit_approval(case["id"],operator={"verified":True,"operator_id":"rel","role":"release-manager"})
    submit_approval(case["id"],operator={"verified":True,"operator_id":"ops","role":"ops"})
    now=datetime.now(timezone.utc); start=(now-timedelta(minutes=5)).isoformat(); end=(now+timedelta(minutes=5)).isoformat()
    monkeypatch.setattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_FREEZE_WINDOWS_JSON",json.dumps([{"starts_at":start,"ends_at":end,"reason":"incident freeze"}]))
    result=evaluate_case(case["id"])
    assert result["freeze"]["frozen"] is True
    assert "production_freeze_active" in result["blockers"]


def test_release_train_can_be_required_and_bound_to_case(tmp_path,monkeypatch):
    case=_case_ready(tmp_path,monkeypatch)
    monkeypatch.setattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_RELEASE_TRAIN_REQUIRED",True)
    from app.improvement_production_governance import create_train, assign_release_train, evaluate_case
    assert "release_train_required" in evaluate_case(case["id"])["blockers"]
    now=datetime.now(timezone.utc)
    train=create_train(name="September Train",window_start=(now-timedelta(hours=1)).isoformat(),window_end=(now+timedelta(hours=2)).isoformat(),timezone_name="UTC",operator={"verified":True,"operator_id":"ops","role":"ops"})
    assigned=assign_release_train(case["id"],train["id"],operator={"verified":True,"operator_id":"ops","role":"ops"})
    assert assigned["release_train_id"] == train["id"]
    assert "release_train_required" not in evaluate_case(case["id"])["blockers"]


def test_immutable_lock_requires_quorum_and_prevents_input_changes(tmp_path,monkeypatch):
    case=_case_ready(tmp_path,monkeypatch)
    from app.improvement_production_governance import submit_approval, lock_case, attach_change_ticket
    with pytest.raises(ValueError): lock_case(case["id"],operator={"verified":True,"operator_id":"rel","role":"release-manager"},confirm=True)
    submit_approval(case["id"],operator={"verified":True,"operator_id":"rel","role":"release-manager"})
    submit_approval(case["id"],operator={"verified":True,"operator_id":"ops","role":"ops"})
    result=lock_case(case["id"],operator={"verified":True,"operator_id":"rel","role":"release-manager"},confirm=True)
    assert result["case"]["locked_at"]
    assert result["case"]["lock_signature"]
    with pytest.raises(ValueError):
        attach_change_ticket(case["id"],system="jira",reference="REL-141",url=None,operator={"verified":True,"operator_id":"rel","role":"release-manager"})


def test_signed_deployment_package_contains_no_credentials_or_execution_path(tmp_path,monkeypatch):
    case=_case_ready(tmp_path,monkeypatch)
    from app.improvement_production_governance import submit_approval, lock_case, build_deployment_package
    submit_approval(case["id"],operator={"verified":True,"operator_id":"rel","role":"release-manager"})
    submit_approval(case["id"],operator={"verified":True,"operator_id":"ops","role":"ops"})
    lock_case(case["id"],operator={"verified":True,"operator_id":"rel","role":"release-manager"},confirm=True)
    result=build_deployment_package(case["id"],operator={"verified":True,"operator_id":"ops","role":"ops"},confirm=True)
    pkg=result["package"]
    assert pkg["signature"]
    assert pkg["payload"]["safety"]["production_credentials_included"] is False
    assert pkg["payload"]["safety"]["backend_can_execute_production"] is False
    encoded=json.dumps(pkg["payload"]).lower()
    assert "operator-token" not in encoded and "password" not in encoded
    assert result["production_deployment_supported"] is False


def test_package_generation_rechecks_runtime_freeze_after_lock(tmp_path,monkeypatch):
    case=_case_ready(tmp_path,monkeypatch)
    from app.improvement_production_governance import submit_approval, lock_case, build_deployment_package
    submit_approval(case["id"],operator={"verified":True,"operator_id":"rel","role":"release-manager"})
    submit_approval(case["id"],operator={"verified":True,"operator_id":"ops","role":"ops"})
    lock_case(case["id"],operator={"verified":True,"operator_id":"rel","role":"release-manager"},confirm=True)
    now=datetime.now(timezone.utc)
    monkeypatch.setattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_FREEZE_WINDOWS_JSON",json.dumps([{"starts_at":(now-timedelta(minutes=1)).isoformat(),"ends_at":(now+timedelta(minutes=10)).isoformat()}]))
    with pytest.raises(ValueError):
        build_deployment_package(case["id"],operator={"verified":True,"operator_id":"ops","role":"ops"},confirm=True)


def test_package_verification_detects_payload_or_signature_tampering(tmp_path,monkeypatch):
    case=_case_ready(tmp_path,monkeypatch)
    from app.improvement_production_governance import submit_approval, lock_case, build_deployment_package, verify_deployment_package
    submit_approval(case["id"],operator={"verified":True,"operator_id":"rel","role":"release-manager"})
    submit_approval(case["id"],operator={"verified":True,"operator_id":"ops","role":"ops"})
    lock_case(case["id"],operator={"verified":True,"operator_id":"rel","role":"release-manager"},confirm=True)
    package=build_deployment_package(case["id"],operator={"verified":True,"operator_id":"ops","role":"ops"},confirm=True)["package"]
    assert verify_deployment_package(package["id"])["valid"] is True
    with get_db() as conn:
        conn.execute("UPDATE improvement_production_deployment_packages SET signature='tampered' WHERE id=?",(package["id"],)); conn.commit()
    checked=verify_deployment_package(package["id"])
    assert checked["signature_valid"] is False
    assert checked["valid"] is False


def test_unauthorized_role_cannot_approve_or_lock(tmp_path,monkeypatch):
    case=_case_ready(tmp_path,monkeypatch)
    from app.improvement_production_governance import submit_approval, lock_case
    with pytest.raises(ValueError): submit_approval(case["id"],operator={"verified":True,"operator_id":"dev","role":"developer"})
    with pytest.raises(ValueError): lock_case(case["id"],operator={"verified":True,"operator_id":"ops","role":"ops"},confirm=True)


def test_part14_routes_present_and_production_deploy_routes_absent(tmp_path,monkeypatch):
    _workspace(tmp_path,monkeypatch)
    from app.main import app
    paths={r.path for r in app.routes}
    required={
        "/improvements/production-governance/capabilities",
        "/improvements/production-governance/freeze-status",
        "/improvements/production-governance/cases",
        "/improvements/production-governance/cases/{case_id}/change-ticket",
        "/improvements/production-governance/cases/{case_id}/rollout-plan",
        "/improvements/production-governance/cases/{case_id}/approvals",
        "/improvements/production-governance/cases/{case_id}/lock",
        "/improvements/production-governance/cases/{case_id}/deployment-package",
        "/improvements/production-governance/release-trains",
        "/improvements/production-governance/packages/{package_id}",
    }
    assert required.issubset(paths)
    forbidden=("production-deploy","deploy-production","execute-production","promote-production")
    assert not any(any(token in p for token in forbidden) for p in paths)
