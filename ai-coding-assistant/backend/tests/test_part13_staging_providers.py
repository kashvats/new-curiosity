import hashlib
import json
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
    monkeypatch.setattr(settings,"DATABASE_PATH",str(tmp_path/"part13.db"))
    monkeypatch.setattr(settings,"BACKUP_DIR",str(tmp_path/"backups"))
    monkeypatch.setattr(settings,"IMPROVEMENT_RELEASE_ROOT",str(tmp_path/"releases"))
    monkeypatch.setattr(settings,"IMPROVEMENT_RELEASE_BUILD_MODE","validate_only")
    monkeypatch.setattr(settings,"IMPROVEMENT_RELEASE_REQUIRE_CONTAINER_BUILD",False)
    monkeypatch.setattr(settings,"IMPROVEMENT_RELEASE_REQUIRE_VULNERABILITY_REPORT",True)
    monkeypatch.setattr(settings,"IMPROVEMENT_RELEASE_REQUIRE_SIGNATURE",True)
    monkeypatch.setattr(settings,"IMPROVEMENT_RELEASE_SIGNING_KEY","release-test-key")
    monkeypatch.setattr(settings,"IMPROVEMENT_RELEASE_PREVIEW_PROVIDER","none")
    monkeypatch.setattr(settings,"IMPROVEMENT_OPERATOR_CREDENTIALS_JSON",json.dumps({"rel":{"role":"release-manager","token":"secret"}}))
    monkeypatch.setattr(settings,"IMPROVEMENT_STAGING_EXECUTION_ENABLED",False)
    monkeypatch.setattr(settings,"IMPROVEMENT_STAGING_CI_TRIGGER_ENABLED",False)
    monkeypatch.setattr(settings,"IMPROVEMENT_STAGING_OCI_EXECUTION_ENABLED",False)
    monkeypatch.setattr(settings,"IMPROVEMENT_RELEASE_COSIGN_ENABLED",False)
    monkeypatch.setattr(settings,"IMPROVEMENT_GITHUB_STATUS_TOKEN","")
    monkeypatch.setattr(settings,"IMPROVEMENT_GITLAB_STATUS_TOKEN","")
    init_database(); return workspace,project


def _verified_issue(project: Path, issue_id="issue-13"):
    from app.verified_candidate_store import store_verified_repair
    old=(project/"app.py").read_text(encoding="utf-8")
    return store_verified_repair(issue_id=issue_id,project_name="demo",task="change value",
        proposed_changes=[{"action":"modify","path":"app.py","content":"VALUE = 2\n","expected_sha256":hashlib.sha256(old.encode()).hexdigest()}],
        validation={"passed":True,"checks":[{"args":["python","-m","compileall","-q","."],"passed":True,"purpose":"compile"}]},
        review={"passed":True},security={"passed":True},quality={"passed":True})


def _staging_ready(project: Path):
    _verified_issue(project)
    from app.improvement_release_orchestrator import create_release_from_verified, run_release_pipeline, ingest_vulnerability_report, promote_staging_ready
    release=create_release_from_verified(project_name="demo",issue_id="issue-13",commit_sha="abc1234",scm_provider="github",scm_target="org/repo")
    run_release_pipeline(release["id"]); ingest_vulnerability_report(release["id"],{"findings":[]})
    return promote_staging_ready(release["id"],confirm=True)["release"]


def test_part13_schema_and_capabilities(tmp_path,monkeypatch):
    _workspace(tmp_path,monkeypatch)
    from app.improvement_staging_orchestrator import staging_capabilities
    with get_db() as conn:
        tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"improvement_staging_deployments","improvement_release_attestations","improvement_production_release_requests"}.issubset(tables)
    caps=staging_capabilities()
    assert caps["production_deployment_supported"] is False
    assert caps["production_release_request"] is True


def test_kubernetes_manifest_is_staging_scoped_and_execution_defaults_off(tmp_path,monkeypatch):
    _,project=_workspace(tmp_path,monkeypatch); release=_staging_ready(project)
    from app.improvement_staging_orchestrator import deploy_release_to_staging
    dep=deploy_release_to_staging(release["id"],provider="kubernetes",image_ref="ghcr.io/org/app:staging",namespace="ai-staging")
    assert dep["status"] == "planned"
    assert dep["manifest"]["environment"] == "staging"
    assert dep["manifest"]["production"] is False


def test_production_like_staging_targets_are_rejected(tmp_path,monkeypatch):
    _,project=_workspace(tmp_path,monkeypatch); release=_staging_ready(project)
    from app.improvement_staging_orchestrator import deploy_release_to_staging, promote_release_oci
    with pytest.raises(ValueError):
        deploy_release_to_staging(release["id"],provider="kubernetes",image_ref="ghcr.io/org/app:staging",namespace="production")
    with pytest.raises(ValueError):
        promote_release_oci(release["id"],source_ref="ghcr.io/org/app:abc",destination_ref="ghcr.io/org/app:production")


def test_external_staging_deployment_can_be_validated_with_safe_checks_and_slsa(tmp_path,monkeypatch):
    _,project=_workspace(tmp_path,monkeypatch); release=_staging_ready(project)
    from app.improvement_staging_orchestrator import deploy_release_to_staging, run_staging_tests
    from app.improvement_staging_store import list_attestations
    dep=deploy_release_to_staging(release["id"],provider="external",preview_url="https://preview.example.test/r13")
    assert dep["status"] == "ready"
    result=run_staging_tests(dep["id"],checks=[{"kind":"smoke","args":["python","-m","compileall","-q","."]}])
    assert result["passed"] is True
    assert result["deployment"]["status"] == "validated"
    assert any(x["kind"]=="slsa_provenance" for x in list_attestations(release["id"]))


def test_staging_test_failure_never_creates_release_request(tmp_path,monkeypatch):
    _,project=_workspace(tmp_path,monkeypatch); release=_staging_ready(project)
    from app.improvement_staging_orchestrator import deploy_release_to_staging, run_staging_tests, request_production_release
    dep=deploy_release_to_staging(release["id"],provider="external",preview_url="https://preview.example.test/fail")
    result=run_staging_tests(dep["id"],checks=[{"kind":"smoke","args":["python","-m","pytest","definitely_missing_test.py"]}])
    assert result["passed"] is False
    with pytest.raises(ValueError):
        request_production_release(release["id"],operator={"verified":True,"operator_id":"rel","role":"release-manager"},confirm=True)


def test_production_release_request_requires_verified_operator_and_is_non_executable(tmp_path,monkeypatch):
    _,project=_workspace(tmp_path,monkeypatch); release=_staging_ready(project)
    from app.improvement_staging_orchestrator import deploy_release_to_staging, run_staging_tests, request_production_release
    dep=deploy_release_to_staging(release["id"],provider="external",preview_url="https://preview.example.test/ok")
    run_staging_tests(dep["id"],checks=[{"kind":"api","args":["python","-m","compileall","-q","."]}])
    with pytest.raises(ValueError): request_production_release(release["id"],operator={"verified":False,"operator_id":"anon","role":"local"},confirm=True)
    with pytest.raises(ValueError): request_production_release(release["id"],operator={"verified":True,"operator_id":"dev","role":"developer"},confirm=True)
    result=request_production_release(release["id"],operator={"verified":True,"operator_id":"rel","role":"release-manager"},confirm=True,notes="ready")
    assert result["request"]["status"] == "requested"
    assert result["request"]["request"]["evidence_signature"]["signed"] is True
    assert result["production_deployment_executed"] is False
    assert result["production_deployment_supported"] is False


def test_ci_and_oci_adapters_are_planned_by_default(tmp_path,monkeypatch):
    _,project=_workspace(tmp_path,monkeypatch); release=_staging_ready(project)
    from app.improvement_staging_orchestrator import trigger_release_ci, promote_release_oci
    ci=trigger_release_ci(release["id"],provider="github_actions",ref="main",workflow="staging.yml")
    oci=promote_release_oci(release["id"],source_ref="ghcr.io/org/app:abc123",destination_ref="ghcr.io/org/app:staging-abc123")
    assert ci["status"] == "planned"
    assert oci["status"] == "planned"
    assert oci["production"] is False


def test_cosign_is_optional_and_skipped_by_default(tmp_path,monkeypatch):
    _,project=_workspace(tmp_path,monkeypatch); release=_staging_ready(project)
    from app.improvement_staging_orchestrator import generate_slsa_attestation, attest_release_image
    generate_slsa_attestation(release["id"])
    result=attest_release_image(release["id"],image_ref="ghcr.io/org/app:staging@sha256:"+"a"*64)
    assert result["status"] == "skipped"


def test_staging_rollback_tears_down_linked_preview(tmp_path,monkeypatch):
    _,project=_workspace(tmp_path,monkeypatch); release=_staging_ready(project)
    from app.improvement_staging_orchestrator import deploy_release_to_staging, rollback_staging
    from app.improvement_release_store import list_preview_environments
    dep=deploy_release_to_staging(release["id"],provider="external",preview_url="https://preview.example.test/rollback")
    result=rollback_staging(dep["id"])
    assert result["rolled_back_at"]
    assert list_preview_environments(release["id"])[0]["status"] == "torn_down"




def test_expired_preview_auto_teardown_is_staging_only(tmp_path,monkeypatch):
    _,project=_workspace(tmp_path,monkeypatch); release=_staging_ready(project)
    from app.improvement_staging_orchestrator import deploy_release_to_staging, teardown_expired_previews
    from app.improvement_release_store import list_preview_environments
    dep=deploy_release_to_staging(release["id"],provider="external",preview_url="https://preview.example.test/expire")
    with get_db() as conn:
        conn.execute("UPDATE improvement_preview_environments SET expires_at='2000-01-01T00:00:00+00:00' WHERE release_id=?",(release["id"],)); conn.commit()
    result=teardown_expired_previews()
    assert result["expired_candidates"] == 1
    assert result["production_deployment_supported"] is False
    assert list_preview_environments(release["id"])[0]["status"] == "torn_down"

def test_kubernetes_execution_uses_fixed_args_when_explicitly_enabled(tmp_path,monkeypatch):
    _,project=_workspace(tmp_path,monkeypatch); release=_staging_ready(project)
    monkeypatch.setattr(settings,"IMPROVEMENT_STAGING_EXECUTION_ENABLED",True)
    import app.improvement_staging_providers as providers
    captured={}
    class P: returncode=0; stdout="deployment.apps/x configured"; stderr=""
    def fake_run(args,**kwargs): captured.update({"args":args,**kwargs}); return P()
    monkeypatch.setattr(providers.subprocess,"run",fake_run)
    from app.improvement_staging_orchestrator import deploy_release_to_staging
    dep=deploy_release_to_staging(release["id"],provider="kubernetes",image_ref="ghcr.io/org/app:staging",namespace="ai-staging")
    assert dep["status"] == "ready"
    assert captured["args"][:2] == ["kubectl","apply"]
    assert captured["shell"] is False


def test_part13_routes_and_no_production_deploy_route(tmp_path,monkeypatch):
    _workspace(tmp_path,monkeypatch)
    from app.main import app
    paths={r.path for r in app.routes}
    required={
        "/improvements/staging/capabilities",
        "/improvements/staging/releases/{release_id}/ci/trigger",
        "/improvements/staging/releases/{release_id}/oci/promote",
        "/improvements/staging/releases/{release_id}/deployments",
        "/improvements/staging/deployments/{deployment_id}/tests",
        "/improvements/staging/deployments/{deployment_id}/rollback",
        "/improvements/staging/releases/{release_id}/attestations/slsa",
        "/improvements/staging/releases/{release_id}/production-release-request",
    }
    assert required.issubset(paths)
    assert not any("production-deploy" in p or "promote-production" in p for p in paths)
