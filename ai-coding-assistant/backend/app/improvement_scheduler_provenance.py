"""GitHub/GitLab native CI provenance adapters for Part 10."""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, Dict

from app.config import settings
from app.database import get_db, init_database
from app.improvement_secrets import get_secret


def _normalize_status(value: Any) -> str:
    raw = str(value or "pending").strip().lower()
    if raw in {"success", "successful", "passed", "pass", "succeeded", "green"}: return "success"
    if raw in {"failure", "failed", "error", "timed_out", "action_required"}: return "failure"
    if raw in {"cancelled", "canceled", "skipped"}: return "cancelled"
    return "pending"



def record_native_delivery(*, provider: str, project_name: str, delivery_id: str | None, body: bytes) -> Dict[str, Any]:
    if not delivery_id:
        raise ValueError(f"{provider} webhook delivery ID is required for replay protection")
    key = f"{provider}:{str(delivery_id).strip()}"
    if len(key) > 200:
        raise ValueError("Webhook delivery ID is too long")
    init_database()
    now = datetime.now(timezone.utc).isoformat()
    digest = hashlib.sha256(body).hexdigest()
    with get_db() as conn:
        if conn.execute("SELECT 1 FROM improvement_webhook_deliveries WHERE delivery_id=?", (key,)).fetchone():
            raise ValueError("Webhook delivery has already been processed")
        conn.execute(
            "INSERT INTO improvement_webhook_deliveries(delivery_id,project_name,evidence_type,signature_digest,signed_at,received_at) VALUES(?,?,?,?,?,?)",
            (key, project_name, f"{provider}_native", digest, now, now),
        )
        conn.commit()
    return {"delivery_id": key, "authenticated": True, "replay_protected": True}


def verify_github_webhook(*, body: bytes, signature: str | None) -> None:
    secret = get_secret("IMPROVEMENT_GITHUB_WEBHOOK_SECRET")
    if not secret:
        raise ValueError("GitHub webhook secret is not configured")
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(expected, str(signature)):
        raise ValueError("Invalid GitHub webhook signature")


def verify_gitlab_webhook(*, token: str | None) -> None:
    secret = get_secret("IMPROVEMENT_GITLAB_WEBHOOK_TOKEN")
    if not secret:
        raise ValueError("GitLab webhook token is not configured")
    if not token or not hmac.compare_digest(secret, str(token)):
        raise ValueError("Invalid GitLab webhook token")


def github_ci_evidence(payload: Dict[str, Any], *, event: str | None, delivery_id: str | None) -> Dict[str, Any]:
    event = str(event or "unknown")
    workflow = payload.get("workflow_run") or {}
    check = payload.get("check_suite") or {}
    pr = payload.get("pull_request") or {}
    head = pr.get("head") or {}
    if workflow:
        status, sha, branch = workflow.get("conclusion") or workflow.get("status"), workflow.get("head_sha"), workflow.get("head_branch")
    elif check:
        status, sha, branch = check.get("conclusion") or check.get("status"), check.get("head_sha"), check.get("head_branch")
    elif event == "push":
        status, sha, branch = "pending", payload.get("after"), str(payload.get("ref") or "").removeprefix("refs/heads/") or None
    else:
        status, sha, branch = "pending", head.get("sha"), (head.get("ref") or None)
    repo = payload.get("repository") or {}
    return {
        "provider": "github",
        "event_type": event,
        "status": _normalize_status(status),
        "commit_sha": sha,
        "branch": branch,
        "payload": {
            "delivery_id": delivery_id,
            "repository": repo.get("full_name"),
            "workflow_id": workflow.get("id") if workflow else None,
            "run_attempt": workflow.get("run_attempt") if workflow else None,
            "html_url": workflow.get("html_url") or check.get("url") or pr.get("html_url"),
            "provenance_adapter": "github_native",
        },
    }


def gitlab_ci_evidence(payload: Dict[str, Any], *, event: str | None, delivery_id: str | None) -> Dict[str, Any]:
    obj = payload.get("object_attributes") or {}
    commit = payload.get("commit") or {}
    project = payload.get("project") or {}
    return {
        "provider": "gitlab",
        "event_type": str(event or payload.get("object_kind") or "unknown"),
        "status": _normalize_status(obj.get("status") or payload.get("build_status")),
        "commit_sha": obj.get("sha") or commit.get("id") or payload.get("sha"),
        "branch": obj.get("ref") or payload.get("ref"),
        "payload": {
            "delivery_id": delivery_id,
            "project_path": project.get("path_with_namespace"),
            "pipeline_id": obj.get("id"),
            "url": obj.get("url"),
            "provenance_adapter": "gitlab_native",
        },
    }
