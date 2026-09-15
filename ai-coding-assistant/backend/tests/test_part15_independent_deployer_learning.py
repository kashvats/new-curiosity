import hashlib
import hmac
import json
from pathlib import Path

import pytest

from app.config import settings
from app.database import get_db, init_database
from app.improvement_staging_security import canonical_digest


def _workspace(tmp_path, monkeypatch):
    workspace=tmp_path/"workspace"; project=workspace/"demo"; project.mkdir(parents=True)
    (project/"app.py").write_text("VALUE = 1\n",encoding="utf-8")
    monkeypatch.setattr(settings,"WORKSPACE_ROOT",str(workspace))
    monkeypatch.setattr(settings,"DATABASE_PATH",str(tmp_path/"part15.db"))
    monkeypatch.setattr(settings,"IMPROVEMENT_RELEASE_ROOT",str(tmp_path/"releases"))
    monkeypatch.setattr(settings,"IMPROVEMENT_RELEASE_SIGNING_KEY","release-test-key")
    monkeypatch.setattr(settings,"IMPROVEMENT_RELEASE_REQUIRE_SIGNATURE",True)
    monkeypatch.setattr(settings,"IMPROVEMENT_PRODUCTION_OUTCOME_SIGNING_KEY","receipt-test-key")
    monkeypatch.setattr(settings,"IMPROVEMENT_OPERATOR_CREDENTIALS_JSON",json.dumps({
        "rel":{"role":"release-manager","token":"rel-secret"},
        "ops":{"role":"ops","token":"ops-secret"},
    }))
    monkeypatch.setattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_MIN_APPROVALS",2)
    monkeypatch.setattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_REQUIRED_ROLES","release-manager,ops")
    monkeypatch.setattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_ALLOWED_APPROVER_ROLES","release-manager,ops")
    monkeypatch.setattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_CHANGE_TICKET_REQUIRED",True)
    monkeypatch.setattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_FREEZE_WINDOWS_JSON","[]")
    monkeypatch.setattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_RELEASE_TRAIN_REQUIRED",False)
    monkeypatch.setattr(settings,"IMPROVEMENT_PRODUCTION_GOVERNANCE_RELEASE_TRAIN_WINDOW_REQUIRED",False)
    monkeypatch.setattr(settings,"IMPROVEMENT_PRODUCTION_AUTHORIZATION_TTL_MINUTES",10)
    init_database(); return workspace,project


def _production_request():
    from app.improvement_release_store import create_release_candidate, update_release_candidate
    from app.improvement_release_security import sign_digest
    from app.improvement_staging_store import create_production_release_request
    release=create_release_candidate(project_name="demo",issue_id="issue-15",commit_sha="abc1234",scm_provider="github",scm_target="org/repo")
    update_release_candidate(release["id"],status="staging_validated",evidence_bundle={"staging_validated":True})
    evidence_digest=hashlib.sha256(f"release:{release['id']}:validated".encode()).hexdigest()
    signature=sign_digest(evidence_digest,context=f"release:{release['id']}:production-release-request")
    request=create_production_release_request(release_id=release["id"],requested_by="rel",role="release-manager",evidence_digest=evidence_digest,
        request={"human_authorized_handoff":True,"evidence_signature":signature})
    return release,request


def _package(tmp_path,monkeypatch,strategy="rolling"):
    _workspace(tmp_path,monkeypatch); release,request=_production_request()
    from app.improvement_production_governance import (
        attach_artifact_binding, attach_change_ticket, build_deployment_package, create_case_from_request,
        generate_rollout_plan, issue_deployment_authorization, lock_case, submit_approval,
    )
    rel={"verified":True,"operator_id":"rel","role":"release-manager"}; ops={"verified":True,"operator_id":"ops","role":"ops"}
    case=create_case_from_request(request["id"],operator=rel)
    attach_change_ticket(case["id"],system="jira",reference="REL-150",url=None,operator=rel)
    generate_rollout_plan(case["id"],strategy=strategy,operator=rel)
    digest="a"*64; ref=f"ghcr.io/org/app@sha256:{digest}"
    attach_artifact_binding(case["id"],artifact_ref=ref,digest_sha256=digest,kind="oci_image",operator=rel)
    submit_approval(case["id"],operator=rel); submit_approval(case["id"],operator=ops)
    lock_case(case["id"],operator=rel,confirm=True)
    package=build_deployment_package(case["id"],operator=ops,confirm=True)["package"]
    authorization=issue_deployment_authorization(package["id"],operator=ops,confirm=True)["authorization"]
    return release,case,package,authorization


def _sign_receipt(payload):
    digest=canonical_digest(payload)
    signature=hmac.new(b"receipt-test-key",f"production-deployment-receipt:{digest}".encode(),hashlib.sha256).hexdigest()
    return digest,signature


def test_part15_schema_capabilities_and_artifact_binding(tmp_path,monkeypatch):
    _workspace(tmp_path,monkeypatch)
    from app.improvement_production_governance import production_governance_capabilities
    from app.improvement_production_feedback import production_feedback_capabilities
    with get_db() as conn:
        tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        cols={r[1] for r in conn.execute("PRAGMA table_info(improvement_production_governance_cases)")}
    assert {"improvement_production_deployment_authorizations","improvement_production_outcomes"}.issubset(tables)
    assert "artifact_binding_json" in cols
    assert production_governance_capabilities()["fresh_deployment_authorizations"] is True
    assert production_feedback_capabilities()["production_strategy_learning"] is True


def test_artifact_binding_is_approval_bound(tmp_path,monkeypatch):
    _workspace(tmp_path,monkeypatch); _,request=_production_request()
    from app.improvement_production_governance import create_case_from_request,attach_change_ticket,generate_rollout_plan,attach_artifact_binding,submit_approval,evaluate_case
    rel={"verified":True,"operator_id":"rel","role":"release-manager"}; ops={"verified":True,"operator_id":"ops","role":"ops"}
    case=create_case_from_request(request["id"],operator=rel); attach_change_ticket(case["id"],system="jira",reference="REL-150",url=None,operator=rel); generate_rollout_plan(case["id"],strategy="rolling",operator=rel)
    submit_approval(case["id"],operator=rel); submit_approval(case["id"],operator=ops)
    assert evaluate_case(case["id"])["ready_to_lock"] is True
    attach_artifact_binding(case["id"],artifact_ref="ghcr.io/org/app@sha256:"+"b"*64,digest_sha256="b"*64,kind="oci_image",operator=rel)
    result=evaluate_case(case["id"])
    assert result["ready_to_lock"] is False and result["approval_summary"]["stale_approvals"] == 2


def test_fresh_deployment_authorization_is_signed_and_package_bound(tmp_path,monkeypatch):
    _,_,package,authorization=_package(tmp_path,monkeypatch)
    from app.improvement_production_governance import verify_deployment_authorization
    result=verify_deployment_authorization(authorization["id"])
    assert result["valid"] is True
    assert authorization["payload"]["package_digest"] == package["digest_sha256"]
    assert authorization["payload"]["single_use"] is True
    assert authorization["payload"]["safety"]["production_credentials_included"] is False


def test_deployment_authorization_requires_immutable_artifact_binding(tmp_path,monkeypatch):
    _workspace(tmp_path,monkeypatch); _,request=_production_request()
    from app.improvement_production_governance import create_case_from_request,attach_change_ticket,generate_rollout_plan,submit_approval,lock_case,build_deployment_package,issue_deployment_authorization
    rel={"verified":True,"operator_id":"rel","role":"release-manager"}; ops={"verified":True,"operator_id":"ops","role":"ops"}
    case=create_case_from_request(request["id"],operator=rel); attach_change_ticket(case["id"],system="jira",reference="REL-150",url=None,operator=rel); generate_rollout_plan(case["id"],strategy="rolling",operator=rel)
    submit_approval(case["id"],operator=rel); submit_approval(case["id"],operator=ops); lock_case(case["id"],operator=rel,confirm=True)
    package=build_deployment_package(case["id"],operator=ops,confirm=True)["package"]
    with pytest.raises(ValueError): issue_deployment_authorization(package["id"],operator=ops,confirm=True)


def test_signed_production_outcome_is_recorded_and_replay_protected(tmp_path,monkeypatch):
    release,case,package,authorization=_package(tmp_path,monkeypatch)
    from app.improvement_production_feedback import ingest_production_outcome
    payload={"schema":"ai-coding-assistant.production-deployment-receipt.v1","deployment_id":"dep-1","package_id":package["id"],"authorization_id":authorization["id"],"case_id":case["id"],"release_id":release["id"],"project_name":"demo","commit_sha":"abc1234","provider":"kubernetes","rollout_strategy":"rolling","status":"rolled_back","failure_class":"production_slo_halt","metrics":{"error_rate":4.2}}
    digest,signature=_sign_receipt(payload)
    item=ingest_production_outcome(payload=payload,digest_sha256=digest,signature=signature)
    assert item["status"] == "rolled_back"
    with pytest.raises(ValueError): ingest_production_outcome(payload=payload,digest_sha256=digest,signature=signature)


def test_production_rollback_penalizes_future_strategy_and_escalates_risk(tmp_path,monkeypatch):
    release,case,package,authorization=_package(tmp_path,monkeypatch)
    # Link the release issue to a historical candidate strategy.
    with get_db() as conn:
        conn.execute("INSERT INTO improvement_cycles(id,project_name,trigger,state,policy,started_at) VALUES('cy15','demo','manual','DONE','manual','2026-09-15T00:00:00+00:00')")
        conn.execute("INSERT INTO improvement_candidates(id,cycle_id,problem,risk,benefit,confidence,estimated_cost,priority_score,issue_id,status,strategy_key,created_at,updated_at) VALUES('cand15','cy15','fix','low',1,1,1,1,'issue-15','applied','security:unsafe_eval:low','2026-09-15T00:00:00+00:00','2026-09-15T00:00:00+00:00')")
        conn.commit()
    from app.improvement_production_feedback import ingest_production_outcome,production_learning_summary
    payload={"schema":"ai-coding-assistant.production-deployment-receipt.v1","deployment_id":"dep-rollback","package_id":package["id"],"authorization_id":authorization["id"],"case_id":case["id"],"release_id":release["id"],"project_name":"demo","commit_sha":"abc1234","provider":"kubernetes","rollout_strategy":"rolling","status":"rolled_back","failure_class":"production_slo_halt","metrics":{}}
    digest,signature=_sign_receipt(payload); ingest_production_outcome(payload=payload,digest_sha256=digest,signature=signature)
    from app.improvement_learning import apply_outcome_learning
    from app.improvement_risk_controls import apply_failure_cooldowns_and_risk
    candidate={"strategy_key":"security:unsafe_eval:low","priority_score":1.0,"risk":"low","estimated_cost":1,"evidence":{}}
    learned=apply_outcome_learning("demo",[candidate])[0]
    assert learned["production_history_samples"] == 1 and learned["production_rollbacks"] == 1
    assert learned["priority_score"] < 1.0
    guarded=apply_failure_cooldowns_and_risk("demo",[learned])[0]
    assert guarded["risk"] == "medium"
    summary=production_learning_summary("demo")
    assert summary["rolled_back"] == 1
    assert "not model-weight retraining" in summary["learning_type"]


def test_part15_routes_present_and_backend_still_has_no_production_execution_route(tmp_path,monkeypatch):
    _workspace(tmp_path,monkeypatch)
    from app.main import app
    paths={r.path for r in app.routes}
    assert "/improvements/production-governance/cases/{case_id}/artifact-binding" in paths
    assert "/improvements/production-governance/packages/{package_id}/deployment-authorization" in paths
    assert "/improvements/production-outcomes" in paths
    assert "/improvements/production-outcomes/learning" in paths
    forbidden=[p for p in paths if any(term in p.lower() for term in ("deploy-production","production-deploy","execute-production","promote-production"))]
    assert forbidden == []
