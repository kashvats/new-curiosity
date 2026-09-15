import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.security import canonical_digest


def _setup(tmp_path, monkeypatch, *, strategy="canary"):
    monkeypatch.setattr(settings,"PRODUCTION_DEPLOYER_DATABASE_PATH",str(tmp_path/"deployer.db"))
    monkeypatch.setattr(settings,"PRODUCTION_DEPLOYER_PACKAGE_SIGNING_KEY","release-test-key")
    monkeypatch.setattr(settings,"PRODUCTION_DEPLOYER_RECEIPT_SIGNING_KEY","receipt-test-key")
    monkeypatch.setattr(settings,"PRODUCTION_DEPLOYER_OPERATOR_CREDENTIALS_JSON",json.dumps({"dep":{"role":"deployer","token":"dep-secret"}}))
    monkeypatch.setattr(settings,"PRODUCTION_DEPLOYER_EXECUTION_ENABLED",False)
    monkeypatch.setattr(settings,"PRODUCTION_DEPLOYER_OUTCOME_CALLBACK_URL","")
    from app.store import init_db
    init_db()
    digest="a"*64; case_id="case-15"; package_id="pkg-15"; auth_id="auth-15"
    payload={
        "schema":"ai-coding-assistant.production-deployment-package.v1","audience":"independent-production-deployer",
        "case_id":case_id,"release_id":"release-15","project_name":"demo","commit_sha":"abc1234",
        "artifact_binding":{"kind":"oci_image","artifact_ref":f"ghcr.io/org/app@sha256:{digest}","digest_sha256":digest,"immutable":True},
        "rollout_plan":{"strategy":strategy,"stages":[{"traffic_percent":5},{"traffic_percent":100}]},
        "approvals":[{"approver_id":"rel","role":"release-manager","decision":"approve"},{"approver_id":"ops","role":"ops","decision":"approve"}],
        "governance_lock":{"digest":"b"*64,"signature":None},
        "safety":{"production_credentials_included":False,"backend_can_execute_production":False,"automatic_execution_authorized":False,"independent_deployer_must_verify_signature":True},
    }
    lock_sig=hmac.new(b"release-test-key",f"production-governance:{case_id}:lock:{'b'*64}".encode(),hashlib.sha256).hexdigest(); payload["governance_lock"]["signature"]=lock_sig
    package_digest=canonical_digest(payload)
    package_sig=hmac.new(b"release-test-key",f"production-governance:{case_id}:deployment-package:{package_digest}".encode(),hashlib.sha256).hexdigest()
    package={"id":package_id,"case_id":case_id,"digest_sha256":package_digest,"signature":package_sig,"signature_algorithm":"hmac-sha256","payload":payload}
    now=datetime.now(timezone.utc)
    auth_payload={"schema":"ai-coding-assistant.production-deployment-authorization.v1","authorization_id":auth_id,"package_id":package_id,"case_id":case_id,"project_name":"demo","commit_sha":"abc1234","package_digest":package_digest,"artifact_binding":payload["artifact_binding"],"audience":"independent-production-deployer","single_use":True,"runtime_release_controls_verified":True,"issued_at":now.isoformat(),"expires_at":(now+timedelta(minutes=10)).isoformat(),"safety":{"production_credentials_included":False,"backend_can_execute_production":False,"independent_deployer_execution_required":True}}
    auth_digest=canonical_digest(auth_payload)
    auth_sig=hmac.new(b"release-test-key",f"production-deployment-authorization:{auth_id}:{auth_digest}".encode(),hashlib.sha256).hexdigest()
    authorization={"id":auth_id,"package_id":package_id,"case_id":case_id,"digest_sha256":auth_digest,"signature":auth_sig,"signature_algorithm":"hmac-sha256","payload":auth_payload,"expires_at":auth_payload["expires_at"]}
    target={"environment":"production","artifact_ref":payload["artifact_binding"]["artifact_ref"],"artifact_digest":digest,"target_id":"prod-app"}
    operator={"verified":True,"operator_id":"dep","role":"deployer"}
    return package,authorization,target,operator


def test_signed_handoff_verification(tmp_path,monkeypatch):
    package,authorization,_,_=_setup(tmp_path,monkeypatch)
    from app.orchestrator import verify_handoff
    assert verify_handoff(package,authorization)["valid"] is True
    package["payload"]["commit_sha"]="tampered"
    assert verify_handoff(package,authorization)["valid"] is False


def test_deployment_target_must_match_approved_artifact(tmp_path,monkeypatch):
    package,authorization,target,operator=_setup(tmp_path,monkeypatch)
    from app.orchestrator import create_authorized_deployment
    target["artifact_digest"]="c"*64
    with pytest.raises(ValueError): create_authorized_deployment(package=package,authorization=authorization,provider="external",target=target,operator=operator,confirm=True)


def test_credentials_cannot_be_embedded_in_deployment_request(tmp_path,monkeypatch):
    package,authorization,target,operator=_setup(tmp_path,monkeypatch)
    from app.orchestrator import create_authorized_deployment
    target["access_token"]="should-never-be-accepted"
    with pytest.raises(ValueError): create_authorized_deployment(package=package,authorization=authorization,provider="external",target=target,operator=operator,confirm=True)


def test_canary_uses_single_authorization_and_advances_on_healthy_evidence(tmp_path,monkeypatch):
    package,authorization,target,operator=_setup(tmp_path,monkeypatch,strategy="canary")
    from app.orchestrator import create_authorized_deployment,execute_deployment,advance_external_stage
    deployment=create_authorized_deployment(package=package,authorization=authorization,provider="external",target=target,operator=operator,confirm=True)
    deployment=execute_deployment(deployment["id"],operator=operator,confirm=True)
    assert deployment["status"] == "awaiting_external_stages"
    healthy={"health":"healthy","availability":99.99,"error_rate":0.1,"latency_p95_ms":100}
    first=advance_external_stage(deployment["id"],metrics=healthy,action_status="completed",operator=operator,confirm=True)
    assert first["current_stage"] == 1
    final=advance_external_stage(deployment["id"],metrics=healthy,action_status="completed",operator=operator,confirm=True)
    assert final["status"] == "succeeded" and final["receipt"]["signature"]


def test_bad_slo_halts_external_canary_and_creates_signed_receipt(tmp_path,monkeypatch):
    package,authorization,target,operator=_setup(tmp_path,monkeypatch,strategy="canary")
    from app.orchestrator import create_authorized_deployment,execute_deployment,advance_external_stage
    deployment=create_authorized_deployment(package=package,authorization=authorization,provider="external",target=target,operator=operator,confirm=True)
    execute_deployment(deployment["id"],operator=operator,confirm=True)
    bad={"health":"unhealthy","availability":90,"error_rate":12,"latency_p95_ms":9000}
    result=advance_external_stage(deployment["id"],metrics=bad,action_status="completed",operator=operator,confirm=True)
    assert result["status"] == "halted"
    assert result["failure_class"] == "production_slo_halt"
    assert result["receipt"]["payload"]["status"] == "halted"


def test_direct_rolling_execution_is_default_off_without_consuming_authorization(tmp_path,monkeypatch):
    package,authorization,target,operator=_setup(tmp_path,monkeypatch,strategy="rolling")
    # rolling requires kubernetes/ecs; convert approved binding/target to Kubernetes.
    target.update({"namespace":"production","deployment":"demo","container":"app"}); target.pop("target_id")
    from app.orchestrator import create_authorized_deployment,execute_deployment
    from app.store import authorization_used
    deployment=create_authorized_deployment(package=package,authorization=authorization,provider="kubernetes",target=target,operator=operator,confirm=True)
    with pytest.raises(ValueError): execute_deployment(deployment["id"],operator=operator,confirm=True)
    assert authorization_used(authorization["id"]) is False


def test_receipt_signature_matches_backend_contract(tmp_path,monkeypatch):
    package,authorization,target,operator=_setup(tmp_path,monkeypatch,strategy="canary")
    from app.orchestrator import create_authorized_deployment,execute_deployment,abort_deployment
    deployment=create_authorized_deployment(package=package,authorization=authorization,provider="external",target=target,operator=operator,confirm=True)
    execute_deployment(deployment["id"],operator=operator,confirm=True)
    terminal=abort_deployment(deployment["id"],operator=operator,confirm=True)
    receipt=terminal["receipt"]; digest=canonical_digest(receipt["payload"])
    expected=hmac.new(b"receipt-test-key",f"production-deployment-receipt:{digest}".encode(),hashlib.sha256).hexdigest()
    assert receipt["digest_sha256"] == digest
    assert hmac.compare_digest(receipt["signature"],expected)


def test_api_exposes_production_deployer_not_ai_backend(tmp_path,monkeypatch):
    _setup(tmp_path,monkeypatch)
    from app.main import app
    paths={r.path for r in app.routes}
    assert "/deployments/{deployment_id}/execute" in paths
    assert "/deployments/{deployment_id}/rollback" in paths
    assert "/deployments/{deployment_id}/receipt" in paths
