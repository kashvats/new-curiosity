import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.security import canonical_digest, verify_hmac


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(settings,"PRODUCTION_DEPLOYER_DATABASE_PATH",str(tmp_path/"deployer16.db"))
    monkeypatch.setattr(settings,"PRODUCTION_DEPLOYER_PACKAGE_SIGNING_KEY","new-key")
    monkeypatch.setattr(settings,"PRODUCTION_DEPLOYER_PREVIOUS_PACKAGE_SIGNING_KEYS","old-key")
    monkeypatch.setattr(settings,"PRODUCTION_DEPLOYER_RECEIPT_SIGNING_KEY","receipt-new")
    monkeypatch.setattr(settings,"PRODUCTION_DEPLOYER_PREVIOUS_RECEIPT_SIGNING_KEYS","receipt-old")
    monkeypatch.setattr(settings,"PRODUCTION_DEPLOYER_OPERATOR_CREDENTIALS_JSON",json.dumps({"dep":{"role":"deployer","token":"secret"}}))
    monkeypatch.setattr(settings,"PRODUCTION_DEPLOYER_EXECUTION_ENABLED",False)
    from app.store import init_db
    init_db()


def _deployment(tmp_path,monkeypatch):
    _setup(tmp_path,monkeypatch)
    from app.store import create_deployment, record_event, record_observation, update_deployment
    package={"id":"pkg16","case_id":"case16","payload":{"case_id":"case16","release_id":"rel16","project_name":"demo","commit_sha":"abc","rollout_plan":{"strategy":"rolling"}}}
    auth={"id":"auth16","payload":{"authorization_id":"auth16"}}
    dep=create_deployment(package=package,authorization=auth,target={"environment":"production","namespace":"prod","deployment":"app","container":"app"},provider="kubernetes",strategy="rolling",created_by="dep")
    update_deployment(dep["id"],previous_state={"image":"repo/app@sha256:old"})
    record_event(dep["id"],"deployment.created",operator={"operator_id":"dep","role":"deployer"},payload={"x":1})
    record_event(dep["id"],"deployment.checked",operator={"operator_id":"dep","role":"deployer"},payload={"x":2})
    for idx in range(3):
        record_observation(dep["id"],stage_index=idx,metrics={"availability":99.9},passed=True,blockers=[],created_by="dep")
    return dep


def test_previous_package_key_is_accepted_for_rotation(tmp_path,monkeypatch):
    _setup(tmp_path,monkeypatch)
    digest="a"*64
    signature=hmac.new(b"old-key",f"ctx:{digest}".encode(),hashlib.sha256).hexdigest()
    assert verify_hmac(digest,context="ctx",signature=signature) is True


def test_slo_window_and_rollback_drill(tmp_path,monkeypatch):
    dep=_deployment(tmp_path,monkeypatch)
    from app.hardening import evaluate_slo_window, rollback_drill
    result=evaluate_slo_window(dep["id"],min_samples=3,pass_ratio=1.0)
    assert result["passed"] is True and result["samples"] >= 3
    drill=rollback_drill(dep["id"])
    assert drill["passed"] is True and drill["executed"] is False


def test_audit_chain_detects_tampering(tmp_path,monkeypatch):
    dep=_deployment(tmp_path,monkeypatch)
    from app.hardening import verify_audit_chain
    from app.store import db
    assert verify_audit_chain(dep["id"])["valid"] is True
    with db() as conn:
        conn.execute("UPDATE deployment_events SET payload_json='{}' WHERE deployment_id=? LIMIT 1",(dep["id"],)); conn.commit()
    assert verify_audit_chain(dep["id"])["valid"] is False


def test_migration_chaos_concurrency_and_routes(tmp_path,monkeypatch):
    _setup(tmp_path,monkeypatch)
    from app.hardening import chaos_simulation, concurrency_snapshot, migration_safety_check
    assert migration_safety_check()["passed"] is True
    assert chaos_simulation(scenario="callback_unavailable")["passed"] is True
    assert concurrency_snapshot()["within_limit"] is True
    from app.main import app
    paths={r.path for r in app.routes}
    assert "/hardening/migration-safety" in paths
    assert "/deployments/{deployment_id}/audit-chain" in paths
    assert "/deployments/{deployment_id}/slo-window" in paths
