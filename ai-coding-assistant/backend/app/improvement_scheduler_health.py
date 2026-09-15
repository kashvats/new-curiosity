"""Production liveness/readiness diagnostics for the scheduler deployment."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from app.config import settings
from app.database import get_db, init_database
from app.improvement_scheduler_ha import coordination_status
from app.improvement_scheduler_integrations import integration_status
from app.improvement_secrets import secret_provider_status


def liveness_probe() -> Dict[str, Any]:
    return {"status": "live", "service": settings.APP_NAME, "automatic_source_apply_enabled": False}


def readiness_probe() -> Dict[str, Any]:
    checks: list[Dict[str, Any]] = []
    try:
        init_database()
        with get_db() as conn:
            conn.execute("SELECT 1").fetchone()
        checks.append({"name": "database", "passed": True})
    except Exception as exc:
        checks.append({"name": "database", "passed": False, "message": str(exc)[:300]})

    workspace = Path(str(settings.WORKSPACE_ROOT))
    checks.append({"name": "workspace", "passed": workspace.exists(), "path": str(workspace)})

    coordination = coordination_status()
    coord_ok = bool(coordination.get("configured", True))
    if bool(getattr(settings, "IMPROVEMENT_PROBE_REQUIRE_COORDINATION", True)):
        checks.append({"name": "coordination", "passed": coord_ok, "backend": coordination.get("lease_backend"), "detail": coordination.get("detail")})

    secret_status = secret_provider_status()
    secret_ok = secret_status.get("provider") == "env" or bool(secret_status.get("secrets_dir_available"))
    checks.append({"name": "secrets_provider", "passed": secret_ok, "provider": secret_status.get("provider")})

    integrations = integration_status()
    checks.append({"name": "integrations", "passed": True, "configured": {
        "alert_webhook": integrations.get("alert_webhook_configured"), "otel": integrations.get("otel_export_configured")
    }})

    ready = all(bool(item.get("passed")) for item in checks)
    return {
        "status": "ready" if ready else "not_ready", "ready": ready, "checks": checks,
        "scheduled_source_apply_enabled": False, "automatic_source_apply_enabled": False,
    }
