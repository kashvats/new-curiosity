"""Privacy-preserving LLM usage telemetry for v1.1.

Only model/provider, durations and size/token estimates are persisted. Prompt and
completion contents are deliberately not stored here.
"""
from __future__ import annotations

from datetime import datetime, timezone
import uuid
from typing import Any, Dict, List

from app.config import settings
from app.database import get_db, init_database, get_db_path


_SCHEMA_DB_PATH: str | None = None


def _ensure_schema() -> None:
    global _SCHEMA_DB_PATH
    current = get_db_path()
    if _SCHEMA_DB_PATH != current:
        init_database()
        _SCHEMA_DB_PATH = current


def record_model_usage(
    *, provider: str, model: str, operation: str, prompt_chars: int,
    output_chars: int, duration_ms: int, success: bool, error_type: str = "",
) -> None:
    if not getattr(settings, "V11_MODEL_USAGE_TELEMETRY_ENABLED", True):
        return
    try:
        _ensure_schema()
        now = datetime.now(timezone.utc).isoformat()
        estimated_input = max(0, round(int(prompt_chars) / 4))
        estimated_output = max(0, round(int(output_chars) / 4))
        with get_db() as conn:
            conn.execute(
                """INSERT INTO v11_model_usage
                   (id,provider,model,operation,prompt_chars,output_chars,estimated_input_tokens,
                    estimated_output_tokens,duration_ms,success,error_type,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()), provider, model, operation, int(prompt_chars), int(output_chars),
                    estimated_input, estimated_output, int(duration_ms), 1 if success else 0,
                    (error_type or "")[:200], now,
                ),
            )
            conn.commit()
    except Exception:
        # Telemetry must never break an LLM call.
        return


def model_usage_summary(*, limit: int = 1000) -> Dict[str, Any]:
    _ensure_schema(); limit = max(1, min(int(limit), 10_000))
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM v11_model_usage ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    groups: dict[str, dict[str, Any]] = {}
    total_in = total_out = total_ms = failures = 0
    for row in rows:
        item = dict(row)
        key = f"{item.get('provider')}:{item.get('model')}"
        g = groups.setdefault(key, {
            "provider": item.get("provider"), "model": item.get("model"), "calls": 0,
            "failures": 0, "estimated_input_tokens": 0, "estimated_output_tokens": 0,
            "duration_ms": 0,
        })
        g["calls"] += 1
        g["failures"] += 0 if item.get("success") else 1
        g["estimated_input_tokens"] += int(item.get("estimated_input_tokens") or 0)
        g["estimated_output_tokens"] += int(item.get("estimated_output_tokens") or 0)
        g["duration_ms"] += int(item.get("duration_ms") or 0)
        total_in += int(item.get("estimated_input_tokens") or 0)
        total_out += int(item.get("estimated_output_tokens") or 0)
        total_ms += int(item.get("duration_ms") or 0)
        failures += 0 if item.get("success") else 1
    models: List[Dict[str, Any]] = []
    for g in groups.values():
        calls = g["calls"]
        g["avg_duration_ms"] = round(g["duration_ms"] / calls, 1) if calls else 0
        models.append(g)
    models.sort(key=lambda x: (-x["calls"], str(x["model"])))
    return {
        "calls_sampled": len(rows),
        "failures": failures,
        "estimated_input_tokens": total_in,
        "estimated_output_tokens": total_out,
        "duration_ms": total_ms,
        "models": models,
        "token_note": "Token counts are conservative char/4 estimates so local and remote providers are comparable; prompt contents are not stored.",
    }
