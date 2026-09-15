"""Part 10 external delivery integrations for scheduler alerts and telemetry."""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from urllib.parse import quote, urlparse

import httpx

from app.config import settings
from app.database import get_db, init_database
from app.improvement_secrets import get_secret


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _validate_endpoint(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Integration endpoint must be an HTTP(S) URL without embedded credentials")
    if parsed.scheme == "http" and not bool(getattr(settings, "IMPROVEMENT_INTEGRATION_ALLOW_HTTP", False)):
        raise ValueError("Plain HTTP integration endpoints are disabled")


def integration_status() -> Dict[str, Any]:
    alert_url = str(getattr(settings, "IMPROVEMENT_ALERT_WEBHOOK_URL", "") or "").strip()
    otel_endpoint = str(getattr(settings, "IMPROVEMENT_OTEL_EXPORTER_ENDPOINT", "") or "").strip()
    return {
        "alert_webhook_configured": bool(alert_url),
        "alert_webhook_signed": bool(get_secret("IMPROVEMENT_ALERT_WEBHOOK_SIGNING_SECRET")),
        "otel_export_configured": bool(otel_endpoint),
        "github_status_publishing_configured": bool(get_secret("IMPROVEMENT_GITHUB_STATUS_TOKEN")),
        "gitlab_status_publishing_configured": bool(get_secret("IMPROVEMENT_GITLAB_STATUS_TOKEN")),
        "delivery_max_attempts": max(1, int(getattr(settings, "IMPROVEMENT_INTEGRATION_MAX_ATTEMPTS", 5))),
        "allow_plain_http": bool(getattr(settings, "IMPROVEMENT_INTEGRATION_ALLOW_HTTP", False)),
        "automatic_source_apply_enabled": False,
    }


def enqueue_alert_delivery(alert: Dict[str, Any]) -> Dict[str, Any] | None:
    url = str(getattr(settings, "IMPROVEMENT_ALERT_WEBHOOK_URL", "") or "").strip()
    if not url:
        return None
    _validate_endpoint(url)
    init_database()
    delivery_id = str(uuid.uuid4())
    with get_db() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO improvement_scheduler_deliveries
               (id, kind, source_id, target, status, attempts, created_at)
               VALUES (?, 'alert_webhook', ?, ?, 'pending', 0, ?)""",
            (delivery_id, alert["id"], url, _now()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM improvement_scheduler_deliveries WHERE kind='alert_webhook' AND source_id=?", (alert["id"],)).fetchone()
    return dict(row) if row else None


def _alert_payload(alert_id: str) -> Dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM improvement_scheduler_alerts WHERE id=?", (alert_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    try:
        item["details"] = json.loads(item.pop("details_json", "{}"))
    except Exception:
        item["details"] = {}
    return {"event": "scheduler.alert", "alert": item, "source_apply_enabled": False}


def _delivery_headers(body: bytes) -> Dict[str, str]:
    headers = {"Content-Type": "application/json", "User-Agent": "ai-coding-assistant-scheduler/1.0"}
    secret = get_secret("IMPROVEMENT_ALERT_WEBHOOK_SIGNING_SECRET")
    if secret:
        timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        digest = hmac.new(secret.encode("utf-8"), timestamp.encode("utf-8") + b"." + body, hashlib.sha256).hexdigest()
        headers["X-AI-Scheduler-Timestamp"] = timestamp
        headers["X-AI-Scheduler-Signature"] = "sha256=" + digest
    return headers


def _retry_state(attempts_after: int) -> tuple[str, str | None]:
    max_attempts = max(1, int(getattr(settings, "IMPROVEMENT_INTEGRATION_MAX_ATTEMPTS", 5)))
    if attempts_after >= max_attempts:
        return "dead_letter", None
    base = max(1, int(getattr(settings, "IMPROVEMENT_INTEGRATION_BACKOFF_BASE_SECONDS", 30)))
    maximum = max(base, int(getattr(settings, "IMPROVEMENT_INTEGRATION_BACKOFF_MAX_SECONDS", 3600)))
    delay = min(maximum, base * (2 ** max(0, attempts_after - 1)))
    return "retry", (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()


def flush_alert_deliveries(*, limit: int = 20) -> Dict[str, Any]:
    init_database()
    limit = max(1, min(int(limit), 100))
    now = _now()
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM improvement_scheduler_deliveries
               WHERE kind='alert_webhook' AND status IN ('pending','retry')
                 AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
               ORDER BY created_at ASC LIMIT ?""",
            (now, limit),
        ).fetchall()
    delivered = failed = dead_lettered = 0
    for raw in rows:
        item = dict(raw); status_code = None
        try:
            _validate_endpoint(item["target"])
            payload = _alert_payload(item["source_id"])
            if not payload:
                raise RuntimeError("Alert no longer exists")
            body = _canonical_json(payload).encode("utf-8")
            timeout = max(0.5, float(getattr(settings, "IMPROVEMENT_INTEGRATION_HTTP_TIMEOUT_SECONDS", 5.0)))
            response = httpx.post(item["target"], content=body, headers=_delivery_headers(body), timeout=timeout)
            status_code = getattr(response, "status_code", None)
            response.raise_for_status()
            status = "delivered"; error = None; next_attempt = None; delivered += 1
        except Exception as exc:
            attempts_after = int(item.get("attempts") or 0) + 1
            status, next_attempt = _retry_state(attempts_after)
            error = str(exc)[:500]; failed += 1
            if status == "dead_letter": dead_lettered += 1
        attempted_at = _now()
        with get_db() as conn:
            conn.execute(
                """UPDATE improvement_scheduler_deliveries
                   SET status=?, attempts=attempts+1, last_attempt_at=?,
                       delivered_at=CASE WHEN ?='delivered' THEN ? ELSE delivered_at END,
                       last_error=?, next_attempt_at=?,
                       dead_lettered_at=CASE WHEN ?='dead_letter' THEN ? ELSE dead_lettered_at END,
                       last_status_code=? WHERE id=?""",
                (status, attempted_at, status, attempted_at, error, next_attempt, status, attempted_at, status_code, item["id"]),
            )
            conn.commit()
    return {"processed": len(rows), "delivered": delivered, "failed": failed, "dead_lettered": dead_lettered}

def list_integration_deliveries(*, limit: int = 100) -> list[Dict[str, Any]]:
    init_database(); limit = max(1, min(int(limit), 500))
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM improvement_scheduler_deliveries ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


def _otel_headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    raw = str(getattr(settings, "IMPROVEMENT_OTEL_EXPORTER_HEADERS_JSON", "{}") or "{}").strip() or "{}"
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            for key, value in parsed.items():
                if key and value is not None:
                    headers[str(key)] = str(value)
    except Exception:
        pass
    return headers


def _otel_payload(rows: list[Dict[str, Any]]) -> Dict[str, Any]:
    records = []
    for row in rows:
        attrs = row.get("attributes") or {}
        records.append({
            "timeUnixNano": str(int(datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00")).timestamp() * 1_000_000_000)),
            "severityText": "INFO",
            "body": {"stringValue": str(row.get("event_type") or "scheduler_event")},
            "attributes": [
                {"key": "project_name", "value": {"stringValue": str(row.get("project_name") or "")}},
                {"key": "schedule_id", "value": {"stringValue": str(row.get("schedule_id") or "")}},
                {"key": "run_id", "value": {"stringValue": str(row.get("run_id") or "")}},
                {"key": "attributes_json", "value": {"stringValue": _canonical_json(attrs)}},
            ],
        })
    return {"resourceLogs": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "ai-coding-assistant-scheduler"}}]}, "scopeLogs": [{"scope": {"name": "scheduler"}, "logRecords": records}]}]}


def flush_otel_telemetry(*, limit: int = 100) -> Dict[str, Any]:
    endpoint = str(getattr(settings, "IMPROVEMENT_OTEL_EXPORTER_ENDPOINT", "") or "").strip()
    if not endpoint:
        return {"configured": False, "processed": 0, "exported": 0}
    _validate_endpoint(endpoint)
    init_database(); limit = max(1, min(int(limit), 500))
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM improvement_scheduler_telemetry WHERE otel_exported_at IS NULL ORDER BY created_at ASC LIMIT ?", (limit,)).fetchall()
    decoded = []
    for row in rows:
        item = dict(row)
        try: item["attributes"] = json.loads(item.get("attributes_json") or "{}")
        except Exception: item["attributes"] = {}
        decoded.append(item)
    if not decoded:
        return {"configured": True, "processed": 0, "exported": 0}
    url = endpoint.rstrip("/") + "/v1/logs"
    try:
        timeout = max(0.5, float(getattr(settings, "IMPROVEMENT_INTEGRATION_HTTP_TIMEOUT_SECONDS", 5.0)))
        response = httpx.post(url, json=_otel_payload(decoded), headers=_otel_headers(), timeout=timeout)
        response.raise_for_status()
        exported_at = _now()
        ids = [item["id"] for item in decoded]
        with get_db() as conn:
            conn.executemany("UPDATE improvement_scheduler_telemetry SET otel_exported_at=?, otel_export_error=NULL WHERE id=?", [(exported_at, item_id) for item_id in ids])
            conn.commit()
        return {"configured": True, "processed": len(decoded), "exported": len(decoded), "endpoint": url}
    except Exception as exc:
        with get_db() as conn:
            conn.executemany("UPDATE improvement_scheduler_telemetry SET otel_export_error=? WHERE id=?", [(str(exc)[:500], item["id"]) for item in decoded])
            conn.commit()
        return {"configured": True, "processed": len(decoded), "exported": 0, "error": str(exc)[:500], "endpoint": url}


def queue_status_publication(*, provider: str, project_name: str, commit_sha: str, target: str,
                             state: str, description: str = "", context: str = "ai-coding-assistant/scheduler") -> Dict[str, Any]:
    provider = str(provider).strip().lower()
    if provider not in {"github", "gitlab"}:
        raise ValueError("provider must be github or gitlab")
    if not commit_sha or len(commit_sha) > 160:
        raise ValueError("commit_sha is required")
    target = str(target or "").strip().strip("/")
    if not target or target.startswith("http://") or target.startswith("https://") or ".." in target:
        raise ValueError("target must be a repository/project identifier, not a URL")
    normalized = str(state or "pending").strip().lower()
    if normalized not in {"pending", "success", "failure", "error", "cancelled"}:
        raise ValueError("unsupported publication state")
    item = {
        "id": str(uuid.uuid4()), "provider": provider, "project_name": project_name, "commit_sha": commit_sha,
        "target": target, "state": normalized, "description": str(description or "")[:300],
        "context": str(context or "ai-coding-assistant/scheduler")[:120], "status": "pending", "attempts": 0,
        "created_at": _now(),
    }
    init_database()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO improvement_scheduler_status_publications
               (id,provider,project_name,commit_sha,target,state,description,context,status,attempts,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (item["id"], item["provider"], item["project_name"], item["commit_sha"], item["target"], item["state"],
             item["description"], item["context"], item["status"], 0, item["created_at"]),
        )
        conn.commit()
    return item


def _publication_request(item: Dict[str, Any]) -> tuple[str, Dict[str, str], Dict[str, Any]]:
    provider = item["provider"]
    if provider == "github":
        token = get_secret("IMPROVEMENT_GITHUB_STATUS_TOKEN")
        if not token:
            raise RuntimeError("GitHub status token is not configured")
        target = item["target"]
        if target.count("/") != 1:
            raise ValueError("GitHub target must use owner/repo")
        url = f"https://api.github.com/repos/{target}/statuses/{item['commit_sha']}"
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "User-Agent": "ai-coding-assistant-scheduler/1.0"}
        state = "failure" if item["state"] in {"failure", "error", "cancelled"} else item["state"]
        body = {"state": state, "description": item.get("description") or "AI Coding Assistant scheduler", "context": item.get("context") or "ai-coding-assistant/scheduler"}
        return url, headers, body
    token = get_secret("IMPROVEMENT_GITLAB_STATUS_TOKEN")
    if not token:
        raise RuntimeError("GitLab status token is not configured")
    base = str(getattr(settings, "IMPROVEMENT_GITLAB_API_BASE", "https://gitlab.com/api/v4") or "https://gitlab.com/api/v4").rstrip("/")
    _validate_endpoint(base)
    target = quote(item["target"], safe="")
    url = f"{base}/projects/{target}/statuses/{item['commit_sha']}"
    mapping = {"pending": "pending", "success": "success", "failure": "failed", "error": "failed", "cancelled": "canceled"}
    headers = {"PRIVATE-TOKEN": token, "User-Agent": "ai-coding-assistant-scheduler/1.0"}
    body = {"state": mapping[item["state"]], "name": item.get("context") or "ai-coding-assistant/scheduler", "description": item.get("description") or "AI Coding Assistant scheduler"}
    return url, headers, body


def flush_status_publications(*, limit: int = 20) -> Dict[str, Any]:
    init_database(); limit = max(1, min(int(limit), 100)); now = _now()
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM improvement_scheduler_status_publications
               WHERE status IN ('pending','retry') AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
               ORDER BY created_at ASC LIMIT ?""", (now, limit)).fetchall()
    delivered = failed = dead_lettered = 0
    for raw in rows:
        item = dict(raw)
        try:
            url, headers, body = _publication_request(item)
            timeout = max(0.5, float(getattr(settings, "IMPROVEMENT_INTEGRATION_HTTP_TIMEOUT_SECONDS", 5.0)))
            response = httpx.post(url, json=body, headers=headers, timeout=timeout)
            response.raise_for_status()
            status = "delivered"; error = None; next_attempt = None; delivered += 1
        except Exception as exc:
            status, next_attempt = _retry_state(int(item.get("attempts") or 0) + 1)
            error = str(exc)[:500]; failed += 1
            if status == "dead_letter": dead_lettered += 1
        attempted_at = _now()
        with get_db() as conn:
            conn.execute(
                """UPDATE improvement_scheduler_status_publications SET status=?,attempts=attempts+1,last_attempt_at=?,
                   delivered_at=CASE WHEN ?='delivered' THEN ? ELSE delivered_at END,last_error=?,next_attempt_at=?,
                   dead_lettered_at=CASE WHEN ?='dead_letter' THEN ? ELSE dead_lettered_at END WHERE id=?""",
                (status, attempted_at, status, attempted_at, error, next_attempt, status, attempted_at, item["id"]),
            )
            conn.commit()
    return {"processed": len(rows), "delivered": delivered, "failed": failed, "dead_lettered": dead_lettered}


def list_status_publications(*, project_name: str | None = None, status: str | None = None, limit: int = 100) -> list[Dict[str, Any]]:
    init_database(); limit = max(1, min(int(limit), 500)); where=[]; vals=[]
    if project_name: where.append("project_name=?"); vals.append(project_name)
    if status: where.append("status=?"); vals.append(status)
    sql="SELECT * FROM improvement_scheduler_status_publications"
    if where: sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT ?"; vals.append(limit)
    with get_db() as conn: rows=conn.execute(sql, vals).fetchall()
    return [dict(r) for r in rows]


def retry_dead_letter(delivery_id: str) -> bool:
    init_database()
    with get_db() as conn:
        cur=conn.execute("""UPDATE improvement_scheduler_deliveries SET status='retry',next_attempt_at=NULL,dead_lettered_at=NULL,last_error=NULL
                            WHERE id=? AND status='dead_letter'""", (delivery_id,))
        if not cur.rowcount:
            cur=conn.execute("""UPDATE improvement_scheduler_status_publications SET status='retry',next_attempt_at=NULL,dead_lettered_at=NULL,last_error=NULL
                                WHERE id=? AND status='dead_letter'""", (delivery_id,))
        conn.commit(); return bool(cur.rowcount)

def _otel_trace_payload(rows: list[Dict[str, Any]]) -> Dict[str, Any]:
    spans = []
    for row in rows:
        created = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
        end_ns = int(created.timestamp() * 1_000_000_000)
        duration_ns = max(0, int(float(row.get("duration_ms") or 0.0) * 1_000_000))
        attrs = row.get("attributes") or {}
        attributes = [
            {"key": "project_name", "value": {"stringValue": str(row.get("project_name") or "")}},
            {"key": "schedule_id", "value": {"stringValue": str(row.get("schedule_id") or "")}},
            {"key": "run_id", "value": {"stringValue": str(row.get("run_id") or "")}},
        ]
        for key, value in list(attrs.items())[:50]:
            attributes.append({"key": f"scheduler.{key}", "value": {"stringValue": str(value)[:1000]}})
        span = {
            "traceId": str(row["trace_id"]), "spanId": str(row["span_id"]), "name": str(row["name"]),
            "kind": 1, "startTimeUnixNano": str(max(0, end_ns - duration_ns)), "endTimeUnixNano": str(end_ns),
            "attributes": attributes, "status": {"code": 2 if row.get("status") == "error" else 1},
        }
        if row.get("parent_span_id"): span["parentSpanId"] = str(row["parent_span_id"])
        spans.append(span)
    return {"resourceSpans": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "ai-coding-assistant-scheduler"}}]}, "scopeSpans": [{"scope": {"name": "scheduler.part11"}, "spans": spans}]}]}


def flush_otel_traces(*, limit: int = 100) -> Dict[str, Any]:
    endpoint = str(getattr(settings, "IMPROVEMENT_OTEL_EXPORTER_ENDPOINT", "") or "").strip()
    if not endpoint:
        return {"configured": False, "processed": 0, "exported": 0}
    _validate_endpoint(endpoint); init_database(); limit=max(1,min(int(limit),500))
    with get_db() as conn:
        rows=conn.execute("SELECT * FROM improvement_scheduler_traces WHERE otel_exported_at IS NULL ORDER BY created_at ASC LIMIT ?", (limit,)).fetchall()
    decoded=[]
    for row in rows:
        item=dict(row)
        try: item["attributes"]=json.loads(item.get("attributes_json") or "{}")
        except Exception: item["attributes"]={}
        decoded.append(item)
    if not decoded: return {"configured": True, "processed": 0, "exported": 0}
    url=endpoint.rstrip("/")+"/v1/traces"
    try:
        timeout=max(0.5,float(getattr(settings,"IMPROVEMENT_INTEGRATION_HTTP_TIMEOUT_SECONDS",5.0)))
        response=httpx.post(url,json=_otel_trace_payload(decoded),headers=_otel_headers(),timeout=timeout); response.raise_for_status()
        exported_at=_now()
        with get_db() as conn:
            conn.executemany("UPDATE improvement_scheduler_traces SET otel_exported_at=?,otel_export_error=NULL WHERE id=?", [(exported_at,item["id"]) for item in decoded]); conn.commit()
        return {"configured": True,"processed":len(decoded),"exported":len(decoded),"endpoint":url}
    except Exception as exc:
        with get_db() as conn:
            conn.executemany("UPDATE improvement_scheduler_traces SET otel_export_error=? WHERE id=?", [(str(exc)[:500],item["id"]) for item in decoded]); conn.commit()
        return {"configured": True,"processed":len(decoded),"exported":0,"error":str(exc)[:500],"endpoint":url}


def flush_integrations(*, limit: int = 100) -> Dict[str, Any]:
    return {
        "alerts": flush_alert_deliveries(limit=min(limit, 100)),
        "status_publications": flush_status_publications(limit=min(limit, 100)),
        "otel": flush_otel_telemetry(limit=limit),
        "otel_traces": flush_otel_traces(limit=limit),
        "automatic_source_apply_enabled": False,
    }
