"""Part 10 HA coordination backends for the dry-run scheduler.

The default backend remains SQLite. Optional Redis and PostgreSQL backends are
loaded lazily so local installations do not need extra infrastructure. None of
these primitives authorize source apply; they only coordinate scheduler workers.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from app.config import settings
from app import improvement_scheduler_store as sqlite_store
from app.improvement_secrets import get_secret


def _now() -> datetime:
    return datetime.now(timezone.utc)


def lease_backend_name() -> str:
    raw = str(getattr(settings, "IMPROVEMENT_SCHEDULER_LEASE_BACKEND", "sqlite") or "sqlite").strip().lower()
    return raw if raw in {"sqlite", "redis", "postgres"} else "sqlite"


def _redis_client():
    try:
        import redis  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Redis lease backend requires the 'redis' package") from exc
    url = get_secret("IMPROVEMENT_SCHEDULER_REDIS_URL").strip()
    if not url:
        raise RuntimeError("IMPROVEMENT_SCHEDULER_REDIS_URL is required for the Redis lease backend")
    return redis.Redis.from_url(url, decode_responses=True, socket_timeout=3, socket_connect_timeout=3)


def _postgres_connect():
    try:
        import psycopg  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("PostgreSQL lease backend requires psycopg") from exc
    dsn = get_secret("IMPROVEMENT_SCHEDULER_POSTGRES_DSN").strip()
    if not dsn:
        raise RuntimeError("IMPROVEMENT_SCHEDULER_POSTGRES_DSN is required for the PostgreSQL lease backend")
    conn = psycopg.connect(dsn, connect_timeout=3)
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ai_scheduler_lease_fences (
                lease_key TEXT PRIMARY KEY, last_token BIGINT NOT NULL DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ai_scheduler_leases (
                lease_key TEXT PRIMARY KEY, owner_id TEXT NOT NULL, fence_token BIGINT NOT NULL,
                acquired_at TIMESTAMPTZ NOT NULL, heartbeat_at TIMESTAMPTZ NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL
            )
        """)
    conn.commit()
    return conn


def _redis_lease_key(key: str) -> str:
    prefix = str(getattr(settings, "IMPROVEMENT_SCHEDULER_REDIS_PREFIX", "ai-coding-assistant:scheduler") or "ai-coding-assistant:scheduler")
    return f"{prefix}:lease:{key}"


def _redis_fence_key(key: str) -> str:
    prefix = str(getattr(settings, "IMPROVEMENT_SCHEDULER_REDIS_PREFIX", "ai-coding-assistant:scheduler") or "ai-coding-assistant:scheduler")
    return f"{prefix}:fence:{key}"


def acquire_scheduler_lease(lease_key: str, *, owner_id: str, ttl_seconds: int) -> Dict[str, Any]:
    backend = lease_backend_name()
    ttl = max(5, int(ttl_seconds))
    if backend == "sqlite":
        return sqlite_store.acquire_lease(lease_key, owner_id=owner_id, ttl_seconds=ttl)
    if backend == "redis":
        client = _redis_client()
        token = int(client.incr(_redis_fence_key(lease_key)))
        now = _now()
        payload = json.dumps({"owner_id": owner_id, "fence_token": token, "acquired_at": now.isoformat()})
        acquired = bool(client.set(_redis_lease_key(lease_key), payload, nx=True, ex=ttl))
        if not acquired:
            current = client.get(_redis_lease_key(lease_key))
            return {"acquired": False, "lease_key": lease_key, "backend": "redis", "current": json.loads(current) if current else None}
        return {"acquired": True, "lease_key": lease_key, "owner_id": owner_id, "fence_token": token, "expires_at": (now + timedelta(seconds=ttl)).isoformat(), "backend": "redis"}

    conn = _postgres_connect()
    try:
        now = _now()
        expires = now + timedelta(seconds=ttl)
        with conn.cursor() as cur:
            cur.execute("SELECT owner_id, fence_token, expires_at FROM ai_scheduler_leases WHERE lease_key=%s FOR UPDATE", (lease_key,))
            row = cur.fetchone()
            if row and row[2] > now and row[0] != owner_id:
                conn.rollback()
                return {"acquired": False, "lease_key": lease_key, "owner_id": row[0], "fence_token": int(row[1]), "expires_at": row[2].isoformat(), "backend": "postgres"}
            cur.execute("""
                INSERT INTO ai_scheduler_lease_fences(lease_key,last_token) VALUES(%s,1)
                ON CONFLICT(lease_key) DO UPDATE SET last_token=ai_scheduler_lease_fences.last_token+1
                RETURNING last_token
            """, (lease_key,))
            token = int(cur.fetchone()[0])
            cur.execute("""
                INSERT INTO ai_scheduler_leases(lease_key,owner_id,fence_token,acquired_at,heartbeat_at,expires_at)
                VALUES(%s,%s,%s,%s,%s,%s)
                ON CONFLICT(lease_key) DO UPDATE SET owner_id=EXCLUDED.owner_id,fence_token=EXCLUDED.fence_token,
                    acquired_at=EXCLUDED.acquired_at,heartbeat_at=EXCLUDED.heartbeat_at,expires_at=EXCLUDED.expires_at
            """, (lease_key, owner_id, token, now, now, expires))
        conn.commit()
        return {"acquired": True, "lease_key": lease_key, "owner_id": owner_id, "fence_token": token, "expires_at": expires.isoformat(), "backend": "postgres"}
    finally:
        conn.close()


def heartbeat_scheduler_lease(lease_key: str, *, owner_id: str, ttl_seconds: int, fence_token: int) -> bool:
    backend = lease_backend_name()
    ttl = max(5, int(ttl_seconds))
    if backend == "sqlite":
        return sqlite_store.heartbeat_lease(lease_key, owner_id=owner_id, ttl_seconds=ttl, fence_token=fence_token)
    if backend == "redis":
        client = _redis_client()
        script = """
        local raw=redis.call('GET',KEYS[1]); if not raw then return 0 end
        local v=cjson.decode(raw); if v.owner_id~=ARGV[1] or tostring(v.fence_token)~=ARGV[2] then return 0 end
        redis.call('EXPIRE',KEYS[1],ARGV[3]); return 1
        """
        return bool(getattr(client, "eval")(script, 1, _redis_lease_key(lease_key), owner_id, str(int(fence_token)), str(ttl)))
    conn = _postgres_connect()
    try:
        now = _now(); expires = now + timedelta(seconds=ttl)
        with conn.cursor() as cur:
            cur.execute("UPDATE ai_scheduler_leases SET heartbeat_at=%s,expires_at=%s WHERE lease_key=%s AND owner_id=%s AND fence_token=%s", (now, expires, lease_key, owner_id, int(fence_token)))
            changed = cur.rowcount > 0
        conn.commit(); return changed
    finally:
        conn.close()


def validate_scheduler_lease(lease_key: str, *, owner_id: str, fence_token: int) -> bool:
    backend = lease_backend_name()
    if backend == "sqlite":
        return sqlite_store.validate_lease(lease_key, owner_id=owner_id, fence_token=fence_token)
    if backend == "redis":
        raw = _redis_client().get(_redis_lease_key(lease_key))
        if not raw:
            return False
        try:
            value = json.loads(raw)
            return value.get("owner_id") == owner_id and int(value.get("fence_token") or 0) == int(fence_token)
        except Exception:
            return False
    conn = _postgres_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM ai_scheduler_leases WHERE lease_key=%s AND owner_id=%s AND fence_token=%s AND expires_at>NOW()", (lease_key, owner_id, int(fence_token)))
            return cur.fetchone() is not None
    finally:
        conn.close()


def release_scheduler_lease(lease_key: str, *, owner_id: str, fence_token: int) -> bool:
    backend = lease_backend_name()
    if backend == "sqlite":
        return sqlite_store.release_lease(lease_key, owner_id=owner_id, fence_token=fence_token)
    if backend == "redis":
        client = _redis_client()
        script = """
        local raw=redis.call('GET',KEYS[1]); if not raw then return 0 end
        local v=cjson.decode(raw); if v.owner_id~=ARGV[1] or tostring(v.fence_token)~=ARGV[2] then return 0 end
        return redis.call('DEL',KEYS[1])
        """
        return bool(getattr(client, "eval")(script, 1, _redis_lease_key(lease_key), owner_id, str(int(fence_token))))
    conn = _postgres_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM ai_scheduler_leases WHERE lease_key=%s AND owner_id=%s AND fence_token=%s", (lease_key, owner_id, int(fence_token)))
            changed = cur.rowcount > 0
        conn.commit(); return changed
    finally:
        conn.close()


def coordination_status() -> Dict[str, Any]:
    backend = lease_backend_name()
    configured = True
    detail = None
    if backend == "redis":
        configured = bool(get_secret("IMPROVEMENT_SCHEDULER_REDIS_URL"))
        detail = "redis_url_configured" if configured else "redis_url_missing"
    elif backend == "postgres":
        configured = bool(get_secret("IMPROVEMENT_SCHEDULER_POSTGRES_DSN"))
        detail = "postgres_dsn_configured" if configured else "postgres_dsn_missing"
    return {
        "lease_backend": backend,
        "configured": configured,
        "detail": detail,
        "fencing_enabled": True,
        "leader_election_enabled": bool(getattr(settings, "IMPROVEMENT_SCHEDULER_LEADER_ELECTION_ENABLED", True)),
        "automatic_source_apply_enabled": False,
    }
