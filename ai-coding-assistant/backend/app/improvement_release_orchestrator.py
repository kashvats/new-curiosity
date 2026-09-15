"""Part 12 candidate-to-staging release orchestration.

The release pipeline operates on a copy of the project plus the exact verified repair.
It can build/test/generate evidence and mark a candidate staging-ready after an explicit
operator action. There is intentionally no production-deployment function here.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from app.config import settings
from app.improvement_release_security import (
    generate_sbom, normalize_vulnerability_report, release_signing_status, run_trivy_filesystem_scan,
    sha256_file, sign_digest,
)
from app.improvement_release_store import (
    create_preview_environment, get_release_candidate, list_preview_environments, list_release_artifacts,
    list_release_checks, release_evidence, store_release_artifact, store_release_check, update_preview_environment,
    update_release_candidate,
)
from app.improvement_scheduler_integrations import queue_status_publication
from app.patch_engine import apply_changes
from app.project_paths import resolve_project_root
from app.test_discovery import discover_project_checks
from app.verification_service import verification_service
from app.verified_candidate_store import get_verified_repair

_IGNORE = shutil.ignore_patterns(".git", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "venv", ".venv", "dist", "build", ".next")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _release_root() -> Path:
    root = Path(str(getattr(settings, "IMPROVEMENT_RELEASE_ROOT", "../data/releases") or "../data/releases"))
    if not root.is_absolute():
        root = (Path(__file__).parent.parent / root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _release_dir(release_id: str) -> Path:
    # IDs originate from UUIDs stored by us, but keep the path defense explicit.
    if not release_id or any(ch not in "0123456789abcdef-" for ch in release_id.lower()):
        raise ValueError("Invalid release id")
    target = (_release_root() / release_id).resolve()
    target.relative_to(_release_root())
    target.mkdir(parents=True, exist_ok=True)
    return target


def _queue_scm_status(release: Dict[str, Any], state: str, description: str) -> Dict[str, Any] | None:
    provider = str(release.get("scm_provider") or "").lower()
    target = str(release.get("scm_target") or "")
    sha = str(release.get("commit_sha") or "")
    if provider not in {"github", "gitlab"} or not target or len(sha) < 4:
        return None
    return queue_status_publication(
        provider=provider, project_name=release["project_name"], commit_sha=sha, target=target,
        state=state, description=description[:300], context="ai-coding-assistant/staging-readiness",
    )


def create_release_from_verified(*, project_name: str, issue_id: str, commit_sha: str | None = None,
                                 scm_provider: str | None = None, scm_target: str | None = None,
                                 require_preview: bool = False) -> Dict[str, Any]:
    from app.improvement_release_store import create_release_candidate
    candidate = get_verified_repair(issue_id)
    if not candidate:
        raise KeyError(issue_id)
    if candidate.get("project_name") != project_name:
        raise ValueError("Verified repair belongs to a different project")
    if candidate.get("status") != "verified":
        raise ValueError(f"Only unapplied verified repairs can enter staging orchestration; status={candidate.get('status')}")
    provider = str(scm_provider or "").lower() or None
    if provider and provider not in {"github", "gitlab"}:
        raise ValueError("scm_provider must be github or gitlab")
    release = create_release_candidate(project_name=project_name, issue_id=issue_id, commit_sha=commit_sha,
                                       scm_provider=provider, scm_target=scm_target,
                                       request={"require_preview": bool(require_preview)})
    _queue_scm_status(release, "pending", "Candidate release orchestration created")
    return release


def prepare_release_workspace(release_id: str) -> Dict[str, Any]:
    release = get_release_candidate(release_id)
    if not release: raise KeyError(release_id)
    candidate = get_verified_repair(release["issue_id"])
    if not candidate: raise ValueError("Verified repair no longer exists")
    if candidate.get("status") != "verified":
        raise ValueError(f"Release requires an unapplied verified repair; status={candidate.get('status')}")
    source = resolve_project_root(release["project_name"])
    release_dir = _release_dir(release_id); workspace = release_dir / "workspace"
    if workspace.exists(): shutil.rmtree(workspace)
    shutil.copytree(source, workspace, ignore=_IGNORE)
    results = apply_changes(workspace, candidate.get("proposed_changes") or [])
    manifest = {
        "release_id": release_id, "project_name": release["project_name"], "issue_id": release["issue_id"],
        "source_root": str(source), "workspace": str(workspace), "prepared_at": _now(),
        "changed_files": [r.path for r in results], "production_promotion_allowed": False,
    }
    manifest_path = release_dir / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    digest = sha256_file(manifest_path); signature = sign_digest(digest, context=f"release:{release_id}:candidate-manifest")
    store_release_artifact(release_id, kind="candidate_manifest", name=manifest_path.name, digest_sha256=digest,
                           path=str(manifest_path), signature=signature.get("signature"), signature_algorithm=signature.get("algorithm"), metadata={"changed_files": manifest["changed_files"]})
    store_release_check(release_id, check_type="workspace", status="passed", details={"workspace": str(workspace), "changed_files": manifest["changed_files"]})
    return update_release_candidate(release_id, status="prepared", workspace_path=str(workspace))


def _validation_plan(candidate: Dict[str, Any], workspace: Path) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
    persisted = ((candidate.get("validation") or {}).get("checks") or [])
    targeted = []
    for check in persisted:
        if not isinstance(check, dict) or not isinstance(check.get("args"), list): continue
        targeted.append({"args": check["args"], "cwd": check.get("cwd"), "purpose": check.get("purpose", "Verified candidate check")})
    changed = [str(c.get("path") or "") for c in candidate.get("proposed_changes") or []]
    discovered = discover_project_checks(workspace, changed)
    if not targeted:
        targeted = discovered.get("quick_checks") or []
    return targeted, discovered.get("regression_checks") or []


def validate_release_candidate(release_id: str) -> Dict[str, Any]:
    release = get_release_candidate(release_id)
    if not release: raise KeyError(release_id)
    if not release.get("workspace_path"):
        release = prepare_release_workspace(release_id)
    candidate = get_verified_repair(release["issue_id"])
    workspace = Path(str(release["workspace_path"]))
    targeted, regression = _validation_plan(candidate or {}, workspace)
    result = verification_service.verify_with_regression(str(workspace), targeted, regression)
    store_release_check(release_id, check_type="candidate_validation", status="passed" if result.get("passed") else "failed", details=result)
    regression_result = result.get("regression") or {}
    integration_passed = bool(result.get("passed")) and bool(regression_result.get("passed", True))
    store_release_check(release_id, check_type="integration_tests", status="passed" if integration_passed else "failed",
                        details={"source": "verified_and_discovered_regression_checks", "result": regression_result, "all_checks_passed": bool(result.get("passed"))})
    if not result.get("passed"):
        update_release_candidate(release_id, status="validation_failed", failure_reason="Candidate validation failed")
        _queue_scm_status(release, "failure", "Candidate staging validation failed")
    return result


def container_build_candidate(release_id: str) -> Dict[str, Any]:
    release = get_release_candidate(release_id)
    if not release: raise KeyError(release_id)
    workspace = Path(str(release.get("workspace_path") or ""))
    if not workspace.is_dir():
        release = prepare_release_workspace(release_id); workspace = Path(str(release["workspace_path"]))
    mode = str(getattr(settings, "IMPROVEMENT_RELEASE_BUILD_MODE", "validate_only") or "validate_only").lower()
    if mode != "docker":
        result = {"passed": True, "status": "skipped", "mode": mode, "message": "Container build disabled; validation-only mode", "image": None}
        store_release_check(release_id, check_type="container_build", status="skipped", details=result)
        return result
    dockerfile = workspace / "Dockerfile"
    if not dockerfile.is_file():
        result = {"passed": False, "status": "failed", "mode": "docker", "message": "Dockerfile not found"}
        store_release_check(release_id, check_type="container_build", status="failed", details=result); return result
    network = str(getattr(settings, "IMPROVEMENT_RELEASE_DOCKER_NETWORK", "none") or "none").lower()
    if network not in {"none", "default"}: network = "none"
    tag = f"ai-coding-assistant-candidate:{release_id.replace('-', '')[:20]}"
    args = ["docker", "build", "--network", network, "--label", f"ai.coding.release={release_id}", "-t", tag, "."]
    started = datetime.now(timezone.utc)
    try:
        proc = subprocess.run(args, cwd=workspace, shell=False, capture_output=True, text=True,
                              timeout=max(60, int(getattr(settings, "IMPROVEMENT_RELEASE_BUILD_TIMEOUT_SECONDS", 900))))
        passed = proc.returncode == 0
        result = {"passed": passed, "status": "passed" if passed else "failed", "mode": "docker", "image": tag,
                  "exit_code": proc.returncode, "stdout": (proc.stdout or "")[-20000:], "stderr": (proc.stderr or "")[-20000:],
                  "duration_ms": int((datetime.now(timezone.utc)-started).total_seconds()*1000)}
    except (OSError, subprocess.TimeoutExpired) as exc:
        result = {"passed": False, "status": "failed", "mode": "docker", "image": tag, "message": str(exc)[:2000]}
    store_release_check(release_id, check_type="container_build", status="passed" if result.get("passed") else "failed", details=result)
    return result


def generate_release_sbom(release_id: str) -> Dict[str, Any]:
    release = get_release_candidate(release_id)
    if not release: raise KeyError(release_id)
    workspace = Path(str(release.get("workspace_path") or ""))
    if not workspace.is_dir(): release = prepare_release_workspace(release_id); workspace = Path(str(release["workspace_path"]))
    sbom = generate_sbom(workspace, serial=release_id)
    path = _release_dir(release_id) / "sbom.cdx.json"
    path.write_text(json.dumps(sbom, indent=2, ensure_ascii=False), encoding="utf-8")
    digest = sha256_file(path); signed = sign_digest(digest, context=f"release:{release_id}:sbom")
    artifact = store_release_artifact(release_id, kind="sbom", name=path.name, digest_sha256=digest, path=str(path),
                                      signature=signed.get("signature"), signature_algorithm=signed.get("algorithm"),
                                      metadata={"component_count": len(sbom.get("components") or [])})
    required = bool(getattr(settings, "IMPROVEMENT_RELEASE_REQUIRE_SIGNATURE", True))
    signature_passed = bool(signed.get("signed")) or not required
    store_release_check(release_id, check_type="sbom", status="passed", details={"artifact_id": artifact["id"], "components": len(sbom.get("components") or [])})
    store_release_check(release_id, check_type="artifact_signature", status="passed" if signature_passed else "failed",
                        details={"required": required, "signed": bool(signed.get("signed")), "algorithm": signed.get("algorithm"), "reason": signed.get("reason")})
    return {"artifact": artifact, "sbom": sbom, "signature": signed}


def generate_staging_manifest(release_id: str) -> Dict[str, Any]:
    release = get_release_candidate(release_id)
    if not release: raise KeyError(release_id)
    checks = _latest_check_map(release_id)
    build = (checks.get("container_build") or {}).get("details") or {}
    manifest = {
        "apiVersion": "ai-coding-assistant.openai.com/v1alpha1", "kind": "StagingCandidate",
        "metadata": {"releaseId": release_id, "project": release["project_name"]},
        "spec": {
            "environment": "staging", "issueId": release["issue_id"], "commitSha": release.get("commit_sha"),
            "containerImage": build.get("image"), "buildMode": build.get("mode"),
            "workspaceEphemeral": True, "workspaceTtlHours": int(getattr(settings, "IMPROVEMENT_RELEASE_WORKSPACE_TTL_HOURS", 48)),
            "productionPromotionAllowed": False,
        },
        "generatedAt": _now(),
    }
    path = _release_dir(release_id) / "staging-manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    digest = sha256_file(path); signed = sign_digest(digest, context=f"release:{release_id}:staging-manifest")
    artifact = store_release_artifact(release_id, kind="staging_manifest", name=path.name, digest_sha256=digest, path=str(path),
                                      signature=signed.get("signature"), signature_algorithm=signed.get("algorithm"),
                                      metadata={"environment": "staging", "container_image": build.get("image")})
    required = bool(getattr(settings, "IMPROVEMENT_RELEASE_REQUIRE_SIGNATURE", True))
    status = "passed" if (signed.get("signed") or not required) else "failed"
    store_release_check(release_id, check_type="deployment_manifest", status=status,
                        details={"artifact_id": artifact["id"], "signed": bool(signed.get("signed")), "environment": "staging"})
    return {"artifact": artifact, "manifest": manifest, "signature": signed}


def ingest_vulnerability_report(release_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    release = get_release_candidate(release_id)
    if not release: raise KeyError(release_id)
    encoded = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    if len(encoded) > int(getattr(settings, "IMPROVEMENT_RELEASE_VULN_REPORT_MAX_BYTES", 4_000_000)):
        raise ValueError("Vulnerability report exceeds configured size limit")
    normalized = normalize_vulnerability_report(payload)
    path = _release_dir(release_id) / f"vulnerability-report-{uuid.uuid4().hex[:8]}.json"
    path.write_bytes(encoded)
    digest = sha256_file(path); signed = sign_digest(digest, context=f"release:{release_id}:vulnerability-report")
    artifact = store_release_artifact(release_id, kind="vulnerability_report", name=path.name, digest_sha256=digest, path=str(path),
                                      signature=signed.get("signature"), signature_algorithm=signed.get("algorithm"), metadata={"counts": normalized["counts"]})
    store_release_check(release_id, check_type="vulnerability", status="passed" if normalized["passed"] else "failed",
                        details={**normalized, "artifact_id": artifact["id"]})
    evaluate_release_gates(release_id)
    return {"artifact": artifact, **normalized}


def create_or_register_preview(release_id: str, *, preview_url: str | None = None, provider: str | None = None) -> Dict[str, Any]:
    release = get_release_candidate(release_id)
    if not release: raise KeyError(release_id)
    provider = (provider or str(getattr(settings, "IMPROVEMENT_RELEASE_PREVIEW_PROVIDER", "none"))).lower()
    if provider not in {"none", "external"}: raise ValueError("Preview provider must be none or external")
    if provider == "external":
        if not preview_url or not str(preview_url).startswith(("https://", "http://localhost", "http://127.0.0.1")):
            raise ValueError("External preview URL must use HTTPS (localhost HTTP is allowed for development)")
        status = "ready"
    else:
        preview_url = None; status = "workspace_only"
    expires = (datetime.now(timezone.utc) + timedelta(hours=max(1, int(getattr(settings, "IMPROVEMENT_RELEASE_PREVIEW_TTL_HOURS", 24))))).isoformat()
    preview = create_preview_environment(release_id, provider=provider, preview_url=preview_url, status=status, expires_at=expires,
                                         metadata={"workspace_path": release.get("workspace_path"), "production": False})
    preview_check_status = "passed" if status == "ready" else "skipped"
    store_release_check(release_id, check_type="preview", status=preview_check_status,
                        details={"preview_id": preview["id"], "provider": provider, "url": preview_url, "expires_at": expires})
    evaluate_release_gates(release_id)
    return preview


def _latest_check_map(release_id: str) -> Dict[str, Dict[str, Any]]:
    latest: Dict[str, Dict[str, Any]] = {}
    for item in list_release_checks(release_id): latest[item["check_type"]] = item
    return latest


def _gate_summary(release_id: str) -> Dict[str, Any]:
    release = get_release_candidate(release_id)
    if not release: raise KeyError(release_id)
    checks = _latest_check_map(release_id); request = release.get("request") or {}
    required = ["workspace", "candidate_validation", "integration_tests", "sbom", "artifact_signature", "deployment_manifest", "vulnerability"]
    if bool(getattr(settings, "IMPROVEMENT_RELEASE_REQUIRE_CONTAINER_BUILD", False)): required.append("container_build")
    if bool(request.get("require_preview")): required.append("preview")
    missing = [name for name in required if name not in checks]
    failed = [name for name in required if name in checks and checks[name].get("status") != "passed"]
    # container_build skipped is only acceptable when it is not required.
    passed = not missing and not failed
    return {"passed": passed, "required": required, "missing": missing, "failed": failed,
            "checks": {name: checks.get(name, {}).get("status", "missing") for name in required},
            "production_promotion_allowed": False}


def build_evidence_bundle(release_id: str) -> Dict[str, Any]:
    release = get_release_candidate(release_id)
    if not release: raise KeyError(release_id)
    gate = _gate_summary(release_id)
    payload = {
        "schema": "ai-coding-assistant.release-evidence/v1", "release_id": release_id,
        "project_name": release["project_name"], "issue_id": release["issue_id"], "commit_sha": release.get("commit_sha"),
        "status": release.get("status"), "gates": gate, "checks": list_release_checks(release_id),
        "artifacts": [{k: v for k, v in a.items() if k != "path"} for a in list_release_artifacts(release_id)],
        "previews": list_preview_environments(release_id), "generated_at": _now(), "production_promotion_allowed": False,
    }
    path = _release_dir(release_id) / "release-evidence.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    digest = sha256_file(path); signed = sign_digest(digest, context=f"release:{release_id}:evidence")
    artifact = store_release_artifact(release_id, kind="evidence_bundle", name=path.name, digest_sha256=digest, path=str(path),
                                      signature=signed.get("signature"), signature_algorithm=signed.get("algorithm"), metadata={"gate_passed": gate["passed"]})
    bundle = {"artifact_id": artifact["id"], "digest_sha256": digest, "signature": signed.get("signature"),
              "signature_algorithm": signed.get("algorithm"), "gates": gate, "generated_at": payload["generated_at"]}
    update_release_candidate(release_id, evidence_bundle=bundle)
    return bundle


def evaluate_release_gates(release_id: str) -> Dict[str, Any]:
    release = get_release_candidate(release_id)
    if not release: raise KeyError(release_id)
    gate = _gate_summary(release_id)
    if gate["passed"]:
        status = "waiting_staging_approval"
    elif "vulnerability" in gate["missing"] and bool(getattr(settings, "IMPROVEMENT_RELEASE_REQUIRE_VULNERABILITY_REPORT", True)):
        status = "waiting_vulnerability_evidence"
    else:
        status = "gates_incomplete"
    update_release_candidate(release_id, status=status)
    return {"release_id": release_id, "status": status, "gates": gate, "production_promotion_allowed": False}


def run_release_pipeline(release_id: str) -> Dict[str, Any]:
    release = get_release_candidate(release_id)
    if not release: raise KeyError(release_id)
    update_release_candidate(release_id, status="preparing")
    try:
        prepare_release_workspace(release_id)
        validation = validate_release_candidate(release_id)
        if not validation.get("passed"):
            return {"release": get_release_candidate(release_id), "gates": _gate_summary(release_id), "production_promotion_allowed": False}
        build = container_build_candidate(release_id)
        if bool(getattr(settings, "IMPROVEMENT_RELEASE_REQUIRE_CONTAINER_BUILD", False)) and not build.get("passed"):
            update_release_candidate(release_id, status="build_failed", failure_reason="Required container build failed")
            _queue_scm_status(release, "failure", "Required candidate container build failed")
            return {"release": get_release_candidate(release_id), "build": build, "production_promotion_allowed": False}
        generate_release_sbom(release_id)
        generate_staging_manifest(release_id)
        if str(getattr(settings, "IMPROVEMENT_RELEASE_VULN_SCANNER", "report_only")).lower() == "trivy":
            normalized = run_trivy_filesystem_scan(Path(str(get_release_candidate(release_id)["workspace_path"])))
            store_release_check(release_id, check_type="vulnerability", status="passed" if normalized["passed"] else "failed", details=normalized)
        elif not bool(getattr(settings, "IMPROVEMENT_RELEASE_REQUIRE_VULNERABILITY_REPORT", True)):
            store_release_check(release_id, check_type="vulnerability", status="passed", details={"source": "not_required", "counts": {}})
        if bool((release.get("request") or {}).get("require_preview")) and not list_preview_environments(release_id):
            create_or_register_preview(release_id, provider="none")
        result = evaluate_release_gates(release_id)
        build_evidence_bundle(release_id)
        _queue_scm_status(release, "pending", f"Staging release: {result['status']}")
        return {"release": get_release_candidate(release_id), "gates": result["gates"], "production_promotion_allowed": False}
    except Exception as exc:
        update_release_candidate(release_id, status="pipeline_failed", failure_reason=str(exc))
        store_release_check(release_id, check_type="pipeline", status="failed", details={"message": str(exc)[:2000]})
        _queue_scm_status(release, "failure", "Candidate release pipeline failed")
        raise


def promote_staging_ready(release_id: str, *, confirm: bool) -> Dict[str, Any]:
    if not confirm: raise ValueError("confirm must be true to mark a release staging-ready")
    release = get_release_candidate(release_id)
    if not release: raise KeyError(release_id)
    gate = _gate_summary(release_id)
    if not gate["passed"]:
        raise ValueError(f"Release gates are not satisfied: missing={gate['missing']} failed={gate['failed']}")
    bundle = build_evidence_bundle(release_id)
    updated = update_release_candidate(release_id, status="staging_ready", staging_ready=True, evidence_bundle=bundle)
    store_release_check(release_id, check_type="staging_promotion", status="passed", details={"confirmed": True, "production_promotion_allowed": False})
    _queue_scm_status(updated, "success", "Candidate is staging-ready")
    return {"release": get_release_candidate(release_id), "evidence_bundle": bundle, "production_promotion_allowed": False}


def reject_release(release_id: str, *, reason: str) -> Dict[str, Any]:
    release = get_release_candidate(release_id)
    if not release: raise KeyError(release_id)
    updated = update_release_candidate(release_id, status="rejected", failure_reason=reason or "Rejected by operator")
    _queue_scm_status(updated, "failure", "Candidate release rejected")
    return updated


def cleanup_expired_release_workspaces(*, now: datetime | None = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc); root = _release_root(); removed: list[str] = []; previews_expired: list[str] = []
    ttl = timedelta(hours=max(1, int(getattr(settings, "IMPROVEMENT_RELEASE_WORKSPACE_TTL_HOURS", 48))))
    from app.improvement_release_store import list_release_candidates
    for release in list_release_candidates(limit=500):
        created = datetime.fromisoformat(str(release["created_at"]).replace("Z", "+00:00"))
        if release.get("status") in {"staging_ready", "rejected"} or now - created >= ttl:
            workspace = Path(str(release.get("workspace_path") or ""))
            if workspace.is_dir() and workspace.resolve().is_relative_to(root.resolve()):
                shutil.rmtree(workspace, ignore_errors=True); removed.append(release["id"])
        for preview in list_preview_environments(release["id"]):
            expires = preview.get("expires_at")
            if not expires: continue
            try: expires_dt = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
            except ValueError: continue
            if expires_dt <= now and preview.get("status") not in {"expired", "destroyed"}:
                update_preview_environment(preview["id"], status="expired"); previews_expired.append(preview["id"])
    return {"workspaces_removed": removed, "previews_expired": previews_expired, "production_promotion_allowed": False}


def release_capabilities() -> Dict[str, Any]:
    return {
        "candidate_workspace": True, "container_build_mode": str(getattr(settings, "IMPROVEMENT_RELEASE_BUILD_MODE", "validate_only")),
        "container_build_required": bool(getattr(settings, "IMPROVEMENT_RELEASE_REQUIRE_CONTAINER_BUILD", False)),
        "sbom": "cyclonedx-1.5", "artifact_signing": release_signing_status(),
        "vulnerability_scanner": str(getattr(settings, "IMPROVEMENT_RELEASE_VULN_SCANNER", "report_only")),
        "vulnerability_report_required": bool(getattr(settings, "IMPROVEMENT_RELEASE_REQUIRE_VULNERABILITY_REPORT", True)),
        "preview_provider": str(getattr(settings, "IMPROVEMENT_RELEASE_PREVIEW_PROVIDER", "none")),
        "staging_ready_promotion": True, "production_promotion_allowed": False, "automatic_source_apply_enabled": False,
    }
