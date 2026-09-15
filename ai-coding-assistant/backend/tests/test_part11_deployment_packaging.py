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
    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "part11.db"))
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(settings, "IMPROVEMENT_SCHEDULER_DR_DIR", str(tmp_path / "drills"))
    monkeypatch.setattr(settings, "IMPROVEMENT_SCHEDULER_LEASE_BACKEND", "sqlite")
    monkeypatch.setattr(settings, "IMPROVEMENT_SECRETS_PROVIDER", "env")
    monkeypatch.setattr(settings, "IMPROVEMENT_SECRETS_DIR", str(tmp_path / "secrets"))
    monkeypatch.setattr(settings, "IMPROVEMENT_OPERATOR_CREDENTIALS_JSON", "{}")
    monkeypatch.setattr(settings, "IMPROVEMENT_ALERT_WEBHOOK_URL", "")
    monkeypatch.setattr(settings, "IMPROVEMENT_GITHUB_STATUS_TOKEN", "")
    monkeypatch.setattr(settings, "IMPROVEMENT_GITLAB_STATUS_TOKEN", "")
    init_database()
    return workspace, project


def test_part11_schema_adds_status_trace_and_delivery_retry_state(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    with get_db() as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        cols = {r[1] for r in conn.execute("PRAGMA table_info(improvement_scheduler_deliveries)")}
    assert {"improvement_scheduler_status_publications", "improvement_scheduler_traces"}.issubset(tables)
    assert {"next_attempt_at", "dead_lettered_at", "last_status_code"}.issubset(cols)


def test_file_secret_provider_resolves_without_exposing_value(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    secret_dir = tmp_path / "secrets"; secret_dir.mkdir()
    (secret_dir / "IMPROVEMENT_GITHUB_STATUS_TOKEN").write_text("super-secret\n", encoding="utf-8")
    monkeypatch.setattr(settings, "IMPROVEMENT_SECRETS_PROVIDER", "file")
    from app.improvement_secrets import get_secret, secret_provider_status
    assert get_secret("IMPROVEMENT_GITHUB_STATUS_TOKEN") == "super-secret"
    status = secret_provider_status()
    assert status["provider"] == "file" and status["secrets_dir_available"] is True
    assert "super-secret" not in json.dumps(status)


def test_alert_delivery_uses_backoff_dead_letter_and_manual_retry(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "IMPROVEMENT_ALERT_WEBHOOK_URL", "https://alerts.example.test/hook")
    monkeypatch.setattr(settings, "IMPROVEMENT_INTEGRATION_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(settings, "IMPROVEMENT_INTEGRATION_BACKOFF_BASE_SECONDS", 1)
    from app.improvement_scheduler_observability import create_scheduler_alert
    from app.improvement_scheduler_integrations import flush_alert_deliveries, list_integration_deliveries, retry_dead_letter
    import app.improvement_scheduler_integrations as integrations

    def fail_post(*args, **kwargs):
        raise RuntimeError("sink unavailable")
    monkeypatch.setattr(integrations.httpx, "post", fail_post)
    alert = create_scheduler_alert(project_name="demo", severity="warning", code="test", message="blocked")
    first = flush_alert_deliveries()
    assert first["failed"] == 1
    delivery = list_integration_deliveries()[0]
    assert delivery["status"] == "retry" and delivery["next_attempt_at"]
    with get_db() as conn:
        conn.execute("UPDATE improvement_scheduler_deliveries SET next_attempt_at=? WHERE id=?", ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(), delivery["id"]))
        conn.commit()
    second = flush_alert_deliveries()
    assert second["dead_lettered"] == 1
    delivery = list_integration_deliveries()[0]
    assert delivery["status"] == "dead_letter" and delivery["dead_lettered_at"]
    assert retry_dead_letter(delivery["id"]) is True
    assert list_integration_deliveries()[0]["status"] == "retry"


def test_github_status_publication_uses_fixed_api_host(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "IMPROVEMENT_GITHUB_STATUS_TOKEN", "gh-token")
    from app.improvement_scheduler_integrations import queue_status_publication, flush_status_publications, list_status_publications
    import app.improvement_scheduler_integrations as integrations
    captured = {}
    class Response:
        status_code = 201
        def raise_for_status(self): return None
    def fake_post(url, **kwargs):
        captured.update({"url": url, **kwargs}); return Response()
    monkeypatch.setattr(integrations.httpx, "post", fake_post)
    item = queue_status_publication(provider="github", project_name="demo", commit_sha="abc1234", target="acme/demo", state="success")
    result = flush_status_publications()
    assert result["delivered"] == 1
    assert captured["url"] == "https://api.github.com/repos/acme/demo/statuses/abc1234"
    assert captured["headers"]["Authorization"] == "Bearer gh-token"
    assert list_status_publications()[0]["id"] == item["id"]


def test_gitlab_status_publication_encodes_project_path(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "IMPROVEMENT_GITLAB_STATUS_TOKEN", "gl-token")
    from app.improvement_scheduler_integrations import queue_status_publication, flush_status_publications
    import app.improvement_scheduler_integrations as integrations
    captured = {}
    class Response:
        status_code = 201
        def raise_for_status(self): return None
    def fake_post(url, **kwargs): captured.update({"url": url, **kwargs}); return Response()
    monkeypatch.setattr(integrations.httpx, "post", fake_post)
    queue_status_publication(provider="gitlab", project_name="demo", commit_sha="def5678", target="acme/team/demo", state="failure")
    assert flush_status_publications()["delivered"] == 1
    assert "/projects/acme%2Fteam%2Fdemo/statuses/def5678" in captured["url"]
    assert captured["headers"]["PRIVATE-TOKEN"] == "gl-token"


def test_structured_trace_round_trip(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app.improvement_scheduler_tracing import new_trace_id, record_span, list_traces
    trace_id = new_trace_id()
    span = record_span(trace_id=trace_id, name="scheduler.test", project_name="demo", run_id="r1", duration_ms=12.5, attributes={"gate": "ci"})
    rows = list_traces(run_id="r1")
    assert rows[0]["span_id"] == span["span_id"]
    assert rows[0]["attributes"]["gate"] == "ci"


def test_production_liveness_and_readiness_probes(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app.improvement_scheduler_health import liveness_probe, readiness_probe
    assert liveness_probe()["status"] == "live"
    ready = readiness_probe()
    assert ready["ready"] is True
    assert all(c["passed"] for c in ready["checks"])
    assert ready["automatic_source_apply_enabled"] is False


def test_dr_restore_verification_and_rotation(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "IMPROVEMENT_SCHEDULER_DR_BACKUP_KEEP", 1)
    from app.improvement_scheduler_admin import run_disaster_recovery_drill, verify_disaster_recovery_restore
    first = run_disaster_recovery_drill()
    assert verify_disaster_recovery_restore(first["id"])["verified"] is True
    second = run_disaster_recovery_drill()
    assert second["rotation"]["keep"] == 1
    # Newest backup remains verifiable; the older file may have been rotated.
    assert verify_disaster_recovery_restore(second["id"])["verified"] is True


def test_sqlite_leader_failover_uses_new_fence_token(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app.improvement_scheduler_ha import acquire_scheduler_lease, validate_scheduler_lease
    first = acquire_scheduler_lease("scheduler:leader", owner_id="node-a", ttl_seconds=60)
    with get_db() as conn:
        conn.execute("UPDATE improvement_scheduler_leases SET expires_at=? WHERE lease_key='scheduler:leader'", ((datetime.now(timezone.utc)-timedelta(seconds=5)).isoformat(),))
        conn.commit()
    second = acquire_scheduler_lease("scheduler:leader", owner_id="node-b", ttl_seconds=60)
    assert second["acquired"] is True and second["fence_token"] > first["fence_token"]
    assert not validate_scheduler_lease("scheduler:leader", owner_id="node-a", fence_token=first["fence_token"])
    assert validate_scheduler_lease("scheduler:leader", owner_id="node-b", fence_token=second["fence_token"])


def test_part11_routes_are_registered(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from app.main import app
    paths = {r.path for r in app.routes}
    required = {
        "/health/live", "/health/ready", "/improvements/scheduler/traces",
        "/improvements/scheduler/integrations/status-publications",
        "/improvements/scheduler/integrations/deliveries/{delivery_id}/retry",
        "/improvements/scheduler/admin/dr-drills/{drill_id}/verify-restore",
        "/improvements/scheduler/admin/dr-backups/rotate",
    }
    assert required.issubset(paths)

def test_otel_trace_export_marks_spans_exported(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "IMPROVEMENT_OTEL_EXPORTER_ENDPOINT", "https://otel.example.test")
    from app.improvement_scheduler_tracing import new_trace_id, record_span
    from app.improvement_scheduler_integrations import flush_otel_traces
    import app.improvement_scheduler_integrations as integrations
    captured = {}
    class Response:
        def raise_for_status(self): return None
    def fake_post(url, **kwargs): captured.update({"url": url, **kwargs}); return Response()
    monkeypatch.setattr(integrations.httpx, "post", fake_post)
    record_span(trace_id=new_trace_id(), name="scheduler.run", project_name="demo", run_id="trace-run", duration_ms=5.0)
    result = flush_otel_traces()
    assert result["exported"] == 1 and captured["url"].endswith("/v1/traces")
    with get_db() as conn:
        row = conn.execute("SELECT otel_exported_at FROM improvement_scheduler_traces WHERE run_id='trace-run'").fetchone()
    assert row[0]
