import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.config import settings
from app.database import get_db, init_database


def _workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"; project = workspace / "demo"; project.mkdir(parents=True)
    (project / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (project / "requirements.txt").write_text("fastapi==0.109.0\n", encoding="utf-8")
    (project / "package.json").write_text('{"dependencies":{"react":"18.3.1"}}', encoding="utf-8")
    monkeypatch.setattr(settings, "WORKSPACE_ROOT", str(workspace))
    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "part12.db"))
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(settings, "IMPROVEMENT_RELEASE_ROOT", str(tmp_path / "releases"))
    monkeypatch.setattr(settings, "IMPROVEMENT_RELEASE_BUILD_MODE", "validate_only")
    monkeypatch.setattr(settings, "IMPROVEMENT_RELEASE_REQUIRE_CONTAINER_BUILD", False)
    monkeypatch.setattr(settings, "IMPROVEMENT_RELEASE_REQUIRE_VULNERABILITY_REPORT", True)
    monkeypatch.setattr(settings, "IMPROVEMENT_RELEASE_REQUIRE_SIGNATURE", True)
    monkeypatch.setattr(settings, "IMPROVEMENT_RELEASE_SIGNING_KEY", "release-test-key")
    monkeypatch.setattr(settings, "IMPROVEMENT_RELEASE_PREVIEW_PROVIDER", "none")
    monkeypatch.setattr(settings, "IMPROVEMENT_OPERATOR_CREDENTIALS_JSON", "{}")
    monkeypatch.setattr(settings, "IMPROVEMENT_GITHUB_STATUS_TOKEN", "")
    monkeypatch.setattr(settings, "IMPROVEMENT_GITLAB_STATUS_TOKEN", "")
    init_database()
    return workspace, project


def _verified_issue(project: Path, *, issue_id="issue-12"):
    from app.verified_candidate_store import store_verified_repair
    old = (project / "app.py").read_text(encoding="utf-8")
    return store_verified_repair(
        issue_id=issue_id, project_name="demo", task="change value",
        proposed_changes=[{"action":"modify","path":"app.py","content":"VALUE = 2\n","expected_sha256":hashlib.sha256(old.encode()).hexdigest()}],
        validation={"passed": True, "checks": [{"args":["python","-m","compileall","-q","."],"passed":True,"purpose":"compile"}]},
        review={"passed": True}, security={"passed": True}, quality={"passed": True},
    )


def test_part12_schema_and_capabilities(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app.improvement_release_orchestrator import release_capabilities
    with get_db() as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"improvement_release_candidates","improvement_release_checks","improvement_release_artifacts","improvement_preview_environments"}.issubset(tables)
    caps = release_capabilities()
    assert caps["staging_ready_promotion"] is True
    assert caps["production_promotion_allowed"] is False


def test_release_workspace_applies_patch_without_touching_live_project(tmp_path, monkeypatch):
    _, project = _workspace(tmp_path, monkeypatch); _verified_issue(project)
    from app.improvement_release_orchestrator import create_release_from_verified, prepare_release_workspace
    release = create_release_from_verified(project_name="demo", issue_id="issue-12")
    prepared = prepare_release_workspace(release["id"])
    candidate = Path(prepared["workspace_path"])
    assert (candidate / "app.py").read_text() == "VALUE = 2\n"
    assert (project / "app.py").read_text() == "VALUE = 1\n"


def test_release_pipeline_stops_for_required_vulnerability_evidence(tmp_path, monkeypatch):
    _, project = _workspace(tmp_path, monkeypatch); _verified_issue(project)
    from app.improvement_release_orchestrator import create_release_from_verified, run_release_pipeline
    release = create_release_from_verified(project_name="demo", issue_id="issue-12")
    result = run_release_pipeline(release["id"])
    assert result["release"]["status"] == "waiting_vulnerability_evidence"
    assert result["production_promotion_allowed"] is False


def test_vulnerability_evidence_can_unlock_staging_approval(tmp_path, monkeypatch):
    _, project = _workspace(tmp_path, monkeypatch); _verified_issue(project)
    from app.improvement_release_orchestrator import create_release_from_verified, run_release_pipeline, ingest_vulnerability_report
    from app.improvement_release_store import get_release_candidate
    release = create_release_from_verified(project_name="demo", issue_id="issue-12")
    run_release_pipeline(release["id"])
    report = ingest_vulnerability_report(release["id"], {"findings": []})
    assert report["passed"] is True
    assert get_release_candidate(release["id"])["status"] == "waiting_staging_approval"


def test_high_vulnerability_blocks_staging_gate(tmp_path, monkeypatch):
    _, project = _workspace(tmp_path, monkeypatch); _verified_issue(project)
    from app.improvement_release_orchestrator import create_release_from_verified, run_release_pipeline, ingest_vulnerability_report
    from app.improvement_release_store import get_release_candidate
    release = create_release_from_verified(project_name="demo", issue_id="issue-12")
    run_release_pipeline(release["id"])
    report = ingest_vulnerability_report(release["id"], {"findings": [{"severity":"high","id":"CVE-X","package":"demo"}]})
    assert report["passed"] is False
    assert "high=1" in report["violations"][0]
    assert get_release_candidate(release["id"])["status"] == "gates_incomplete"


def test_sbom_is_cyclonedx_and_signed(tmp_path, monkeypatch):
    _, project = _workspace(tmp_path, monkeypatch); _verified_issue(project)
    from app.improvement_release_orchestrator import create_release_from_verified, prepare_release_workspace, generate_release_sbom
    release = create_release_from_verified(project_name="demo", issue_id="issue-12")
    prepare_release_workspace(release["id"])
    result = generate_release_sbom(release["id"])
    assert result["sbom"]["bomFormat"] == "CycloneDX"
    names = {c["name"] for c in result["sbom"]["components"]}
    assert {"fastapi", "react"}.issubset(names)
    assert result["signature"]["signed"] is True


def test_external_preview_requires_https_and_satisfies_required_preview(tmp_path, monkeypatch):
    _, project = _workspace(tmp_path, monkeypatch); _verified_issue(project)
    from app.improvement_release_orchestrator import create_release_from_verified, run_release_pipeline, ingest_vulnerability_report, create_or_register_preview
    from app.improvement_release_store import get_release_candidate
    release = create_release_from_verified(project_name="demo", issue_id="issue-12", require_preview=True)
    run_release_pipeline(release["id"]); ingest_vulnerability_report(release["id"], {"findings": []})
    assert get_release_candidate(release["id"])["status"] == "gates_incomplete"
    with pytest.raises(ValueError): create_or_register_preview(release["id"], provider="external", preview_url="http://evil.test")
    preview = create_or_register_preview(release["id"], provider="external", preview_url="https://preview.example.test/r/1")
    assert preview["status"] == "ready"
    assert get_release_candidate(release["id"])["status"] == "waiting_staging_approval"


def test_staging_promotion_requires_confirm_and_never_enables_production(tmp_path, monkeypatch):
    _, project = _workspace(tmp_path, monkeypatch); _verified_issue(project)
    from app.improvement_release_orchestrator import create_release_from_verified, run_release_pipeline, ingest_vulnerability_report, promote_staging_ready
    release = create_release_from_verified(project_name="demo", issue_id="issue-12")
    run_release_pipeline(release["id"]); ingest_vulnerability_report(release["id"], {"findings": []})
    with pytest.raises(ValueError): promote_staging_ready(release["id"], confirm=False)
    result = promote_staging_ready(release["id"], confirm=True)
    assert result["release"]["status"] == "staging_ready"
    assert result["release"]["production_promotion_allowed"] is False
    assert result["production_promotion_allowed"] is False


def test_container_build_adapter_uses_fixed_docker_invocation(tmp_path, monkeypatch):
    _, project = _workspace(tmp_path, monkeypatch); _verified_issue(project)
    (project / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    monkeypatch.setattr(settings, "IMPROVEMENT_RELEASE_BUILD_MODE", "docker")
    from app.improvement_release_orchestrator import create_release_from_verified, prepare_release_workspace, container_build_candidate
    import app.improvement_release_orchestrator as orchestrator
    captured = {}
    class P: returncode=0; stdout="ok"; stderr=""
    def fake_run(args, **kwargs): captured.update({"args":args, **kwargs}); return P()
    monkeypatch.setattr(orchestrator.subprocess, "run", fake_run)
    release = create_release_from_verified(project_name="demo", issue_id="issue-12")
    prepare_release_workspace(release["id"]); result = container_build_candidate(release["id"])
    assert result["passed"] is True
    assert captured["args"][:3] == ["docker","build","--network"]
    assert captured["shell"] is False


def test_expired_workspace_cleanup_does_not_delete_release_evidence(tmp_path, monkeypatch):
    _, project = _workspace(tmp_path, monkeypatch); _verified_issue(project)
    from app.improvement_release_orchestrator import create_release_from_verified, prepare_release_workspace, cleanup_expired_release_workspaces
    from app.improvement_release_store import get_release_candidate, list_release_artifacts
    release = create_release_from_verified(project_name="demo", issue_id="issue-12")
    prepared = prepare_release_workspace(release["id"]); workspace = Path(prepared["workspace_path"])
    future = datetime.now(timezone.utc) + timedelta(hours=100)
    result = cleanup_expired_release_workspaces(now=future)
    assert release["id"] in result["workspaces_removed"] and not workspace.exists()
    assert list_release_artifacts(release["id"])
    assert get_release_candidate(release["id"]) is not None


def test_part12_routes_and_no_production_promotion_route(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app.main import app
    paths = {r.path for r in app.routes}
    required = {
        "/improvements/releases/capabilities", "/improvements/releases", "/improvements/releases/{release_id}",
        "/improvements/releases/{release_id}/run", "/improvements/releases/{release_id}/vulnerabilities",
        "/improvements/releases/{release_id}/preview", "/improvements/releases/{release_id}/promote-staging",
        "/improvements/releases/{release_id}/evidence",
    }
    assert required.issubset(paths)
    assert not any("promote-production" in path or "production-deploy" in path for path in paths)
