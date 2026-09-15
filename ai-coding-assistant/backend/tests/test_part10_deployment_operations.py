import hashlib
import hmac
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
    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "part10.db"))
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(settings, "IMPROVEMENT_DRY_RUN_SCHEDULER_ENABLED", False)
    monkeypatch.setattr(settings, "IMPROVEMENT_SCHEDULER_LEASE_BACKEND", "sqlite")
    monkeypatch.setattr(settings, "IMPROVEMENT_SCHEDULER_LEADER_ELECTION_ENABLED", True)
    monkeypatch.setattr(settings, "IMPROVEMENT_ALERT_WEBHOOK_URL", "")
    monkeypatch.setattr(settings, "IMPROVEMENT_ALERT_WEBHOOK_SIGNING_SECRET", "")
    monkeypatch.setattr(settings, "IMPROVEMENT_OTEL_EXPORTER_ENDPOINT", "")
    monkeypatch.setattr(settings, "IMPROVEMENT_INTEGRATION_ALLOW_HTTP", False)
    monkeypatch.setattr(settings, "IMPROVEMENT_GITHUB_WEBHOOK_SECRET", "")
    monkeypatch.setattr(settings, "IMPROVEMENT_GITLAB_WEBHOOK_TOKEN", "")
    monkeypatch.setattr(settings, "IMPROVEMENT_OPERATOR_CREDENTIALS_JSON", "{}")
    monkeypatch.setattr(settings, "IMPROVEMENT_SCHEDULER_DR_DIR", str(tmp_path / "drills"))
    init_database()
    return workspace, project


def test_part10_schema_adds_delivery_dr_and_otel_state(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    with get_db() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        telemetry_cols = {row[1] for row in conn.execute("PRAGMA table_info(improvement_scheduler_telemetry)").fetchall()}
    assert {"improvement_scheduler_deliveries", "improvement_scheduler_dr_drills"}.issubset(tables)
    assert {"otel_exported_at", "otel_export_error"}.issubset(telemetry_cols)


def test_alert_outbox_delivery_is_signed_and_durable(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "IMPROVEMENT_ALERT_WEBHOOK_URL", "https://alerts.example.test/hook")
    monkeypatch.setattr(settings, "IMPROVEMENT_ALERT_WEBHOOK_SIGNING_SECRET", "sink-secret")
    from app.improvement_scheduler_observability import create_scheduler_alert
    from app.improvement_scheduler_integrations import flush_alert_deliveries, list_integration_deliveries
    import app.improvement_scheduler_integrations as integrations

    captured = {}

    class Response:
        def raise_for_status(self):
            return None

    def fake_post(url, *, content=None, headers=None, timeout=None, **kwargs):
        captured.update({"url": url, "content": content, "headers": headers, "timeout": timeout})
        return Response()

    monkeypatch.setattr(integrations.httpx, "post", fake_post)
    alert = create_scheduler_alert(project_name="demo", severity="warning", code="blocked", message="guard blocked")
    pending = list_integration_deliveries()
    assert pending and pending[0]["source_id"] == alert["id"] and pending[0]["status"] == "pending"
    result = flush_alert_deliveries()
    assert result["delivered"] == 1
    assert captured["headers"]["X-AI-Scheduler-Signature"].startswith("sha256=")
    final = list_integration_deliveries()[0]
    assert final["status"] == "delivered"


def test_otel_export_marks_telemetry_exported(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "IMPROVEMENT_OTEL_EXPORTER_ENDPOINT", "https://otel.example.test")
    from app.improvement_scheduler_observability import record_scheduler_telemetry
    from app.improvement_scheduler_integrations import flush_otel_telemetry
    import app.improvement_scheduler_integrations as integrations

    class Response:
        def raise_for_status(self): return None

    captured = {}
    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return Response()
    monkeypatch.setattr(integrations.httpx, "post", fake_post)
    record_scheduler_telemetry(event_type="scheduler_run", project_name="demo", attributes={"status": "completed"})
    result = flush_otel_telemetry()
    assert result["exported"] == 1
    assert captured["url"].endswith("/v1/logs")
    with get_db() as conn:
        row = conn.execute("SELECT otel_exported_at FROM improvement_scheduler_telemetry").fetchone()
    assert row[0]


def test_ha_sqlite_backend_preserves_fencing(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app.improvement_scheduler_ha import acquire_scheduler_lease, coordination_status, release_scheduler_lease, validate_scheduler_lease

    first = acquire_scheduler_lease("scheduler:leader", owner_id="a", ttl_seconds=60)
    assert first["acquired"] is True
    assert validate_scheduler_lease("scheduler:leader", owner_id="a", fence_token=first["fence_token"])
    assert release_scheduler_lease("scheduler:leader", owner_id="a", fence_token=first["fence_token"])
    second = acquire_scheduler_lease("scheduler:leader", owner_id="b", ttl_seconds=60)
    assert second["fence_token"] > first["fence_token"]
    status = coordination_status()
    assert status["lease_backend"] == "sqlite"
    assert status["leader_election_enabled"] is True
    assert status["automatic_source_apply_enabled"] is False


def test_github_provenance_verifies_signature_and_normalizes(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "IMPROVEMENT_GITHUB_WEBHOOK_SECRET", "github-secret")
    from app.improvement_scheduler_provenance import github_ci_evidence, verify_github_webhook

    payload = {"workflow_run": {"conclusion": "success", "head_sha": "abc123", "head_branch": "main", "id": 7}, "repository": {"full_name": "acme/demo"}}
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = "sha256=" + hmac.new(b"github-secret", body, hashlib.sha256).hexdigest()
    verify_github_webhook(body=body, signature=signature)
    evidence = github_ci_evidence(payload, event="workflow_run", delivery_id="d-1")
    assert evidence["status"] == "success"
    assert evidence["commit_sha"] == "abc123"
    assert evidence["branch"] == "main"
    assert evidence["payload"]["provenance_adapter"] == "github_native"


def test_gitlab_provenance_verifies_token_and_normalizes(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "IMPROVEMENT_GITLAB_WEBHOOK_TOKEN", "gitlab-token")
    from app.improvement_scheduler_provenance import gitlab_ci_evidence, verify_gitlab_webhook

    verify_gitlab_webhook(token="gitlab-token")
    payload = {"object_kind": "pipeline", "object_attributes": {"status": "success", "sha": "def456", "ref": "main", "id": 9}, "project": {"path_with_namespace": "acme/demo"}}
    evidence = gitlab_ci_evidence(payload, event="Pipeline Hook", delivery_id="g-1")
    assert evidence["provider"] == "gitlab"
    assert evidence["status"] == "success"
    assert evidence["commit_sha"] == "def456"
    assert evidence["payload"]["provenance_adapter"] == "gitlab_native"


def test_retention_preview_is_non_destructive_and_compaction_deletes_old_rows(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "IMPROVEMENT_WEBHOOK_DELIVERY_RETENTION_DAYS", 1)
    from app.improvement_scheduler_admin import retention_preview, run_retention_compaction

    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    with get_db() as conn:
        conn.execute("INSERT INTO improvement_webhook_deliveries(delivery_id,project_name,evidence_type,signature_digest,signed_at,received_at) VALUES(?,?,?,?,?,?)", ("old-delivery", "demo", "ci", "digest", old, old))
        conn.commit()
    preview = retention_preview()
    assert preview["counts"]["webhook_deliveries"] == 1
    with get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM improvement_webhook_deliveries").fetchone()[0] == 1
    result = run_retention_compaction(vacuum=False)
    assert result["deleted"]["webhook_deliveries"] == 1


def test_disaster_recovery_drill_creates_verified_backup(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app.improvement_scheduler_admin import list_disaster_recovery_drills, run_disaster_recovery_drill
    from app.improvement_scheduler_store import create_schedule

    create_schedule(project_name="demo", name="nightly", interval_minutes=60, require_readiness=False)
    result = run_disaster_recovery_drill()
    assert result["status"] == "passed"
    assert result["integrity_check"].lower() == "ok"
    assert result["schedule_count"] == 1
    assert len(result["sha256"]) == 64
    assert list_disaster_recovery_drills()[0]["id"] == result["id"]


def test_plain_http_integrations_are_blocked_by_default(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "IMPROVEMENT_ALERT_WEBHOOK_URL", "http://127.0.0.1:9999/hook")
    from app.improvement_scheduler_integrations import enqueue_alert_delivery
    import pytest

    with pytest.raises(ValueError, match="Plain HTTP"):
        enqueue_alert_delivery({"id": "a", "project_name": "demo"})


def test_part10_routes_and_status_are_registered(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app.improvement_scheduler import scheduler_status
    from app.main import app

    paths = {route.path for route in app.routes}
    required = {
        "/improvements/scheduler/integrations",
        "/improvements/scheduler/integrations/flush",
        "/improvements/evidence/github",
        "/improvements/evidence/gitlab",
        "/improvements/scheduler/admin/retention/preview",
        "/improvements/scheduler/admin/retention/compact",
        "/improvements/scheduler/admin/dr-drill",
        "/improvements/scheduler/admin/dr-drills",
    }
    assert required.issubset(paths)
    status = scheduler_status()
    assert status["part10_deployment_hardening"] is True
    assert status["coordination"]["lease_backend"] == "sqlite"
    assert status["automatic_source_apply_enabled"] is False
    assert status["scheduled_source_apply_enabled"] is False

def test_native_provenance_delivery_ids_are_replay_protected(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app.improvement_scheduler_provenance import record_native_delivery
    import pytest

    first = record_native_delivery(provider="github", project_name="demo", delivery_id="native-1", body=b"{}")
    assert first["replay_protected"] is True
    with pytest.raises(ValueError, match="already been processed"):
        record_native_delivery(provider="github", project_name="demo", delivery_id="native-1", body=b"{}")
