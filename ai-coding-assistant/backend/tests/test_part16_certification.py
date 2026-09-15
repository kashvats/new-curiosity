import hashlib
import hmac
import json

from app.config import settings
from app.database import init_database


def _setup(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"DATABASE_PATH",str(tmp_path/"part16.db"))
    monkeypatch.setattr(settings,"IMPROVEMENT_CERTIFICATION_SIGNING_KEY","cert-key")
    monkeypatch.setattr(settings,"IMPROVEMENT_OPERATOR_CREDENTIALS_JSON",json.dumps({"ops":{"role":"ops","token":"secret"}}))
    monkeypatch.setattr(settings,"IMPROVEMENT_CERTIFICATION_REQUIRED_GATES","deployer_tests,migration_safety,key_rotation,slo_window,rollback_drill,chaos_failover,security_attack,audit_chain,load_concurrency")
    init_database()


def test_certification_requires_all_fresh_gates(tmp_path,monkeypatch):
    _setup(tmp_path,monkeypatch)
    from app.improvement_certification import evaluate_readiness, record_evidence
    op={"verified":True,"operator_id":"ops","role":"ops"}
    first=evaluate_readiness("demo")
    assert first["eligible"] is False and any(x.startswith("missing_evidence") for x in first["blockers"])
    for gate in ["deployer_tests","migration_safety","key_rotation","slo_window","rollback_drill","chaos_failover","security_attack","audit_chain","load_concurrency"]:
        record_evidence(project_name="demo",gate=gate,passed=True,details={"verified":True},source="pytest",operator=op)
    assert evaluate_readiness("demo")["eligible"] is True


def test_failed_gate_blocks_certificate(tmp_path,monkeypatch):
    _setup(tmp_path,monkeypatch)
    from app.improvement_certification import issue_certificate, record_evidence
    op={"verified":True,"operator_id":"ops","role":"ops"}
    gates=["deployer_tests","migration_safety","key_rotation","slo_window","rollback_drill","chaos_failover","security_attack","audit_chain","load_concurrency"]
    for gate in gates:
        record_evidence(project_name="demo",gate=gate,passed=(gate!="security_attack"),details={},source="pytest",operator=op)
    try:
        issue_certificate(project_name="demo",operator=op,confirm=True)
        assert False, "certificate should be blocked"
    except ValueError:
        pass


def test_signed_certificate_verification_and_tamper_detection(tmp_path,monkeypatch):
    _setup(tmp_path,monkeypatch)
    from app.improvement_certification import issue_certificate, record_evidence, verify_certificate
    from app.database import get_db
    op={"verified":True,"operator_id":"ops","role":"ops"}
    for gate in ["deployer_tests","migration_safety","key_rotation","slo_window","rollback_drill","chaos_failover","security_attack","audit_chain","load_concurrency"]:
        record_evidence(project_name="demo",gate=gate,passed=True,details={},source="pytest",operator=op)
    cert=issue_certificate(project_name="demo",operator=op,confirm=True)
    assert verify_certificate(cert["id"])["valid"] is True
    with get_db() as conn:
        conn.execute("UPDATE improvement_certificates SET signature='tampered' WHERE id=?",(cert["id"],)); conn.commit()
    assert verify_certificate(cert["id"])["valid"] is False


def test_old_production_receipt_key_is_accepted_during_rotation(tmp_path,monkeypatch):
    _setup(tmp_path,monkeypatch)
    monkeypatch.setattr(settings,"IMPROVEMENT_PRODUCTION_OUTCOME_SIGNING_KEY","new-receipt")
    monkeypatch.setattr(settings,"IMPROVEMENT_PRODUCTION_OUTCOME_PREVIOUS_SIGNING_KEYS","old-receipt")
    from app.improvement_production_feedback import _verify_receipt_signature
    digest="b"*64
    signature=hmac.new(b"old-receipt",f"production-deployment-receipt:{digest}".encode(),hashlib.sha256).hexdigest()
    assert _verify_receipt_signature(digest,signature) is True


def test_part16_api_routes_and_no_backend_production_execution(tmp_path,monkeypatch):
    _setup(tmp_path,monkeypatch)
    from app.main import app
    paths={r.path for r in app.routes}
    required={
        "/improvements/certification/capabilities",
        "/improvements/certification/evidence",
        "/improvements/certification/readiness",
        "/improvements/certification/certificates",
        "/improvements/certification/certificates/{certificate_id}/verify",
    }
    assert required.issubset(paths)
    forbidden=[p for p in paths if any(x in p.lower() for x in ("deploy-production","execute-production","promote-production"))]
    assert forbidden == []
