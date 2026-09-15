"""Failure-class cooldowns and historical risk escalation for candidates."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable

from app.config import settings
from app.database import get_db, init_database

_RISK_LEVELS = ["low", "medium", "high", "critical"]
_FAILURE_STATUSES = {
    "validation_failed": "validation_failure",
    "governance_blocked": "governance_failure",
    "budget_exceeded": "budget_failure",
    "rolled_back": "rollback",
}


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _hours(failure_class: str) -> int:
    mapping = {
        "validation_failure": int(settings.IMPROVEMENT_COOLDOWN_VALIDATION_HOURS),
        "governance_failure": int(settings.IMPROVEMENT_COOLDOWN_GOVERNANCE_HOURS),
        "budget_failure": int(settings.IMPROVEMENT_COOLDOWN_BUDGET_HOURS),
        "rollback": int(settings.IMPROVEMENT_COOLDOWN_ROLLBACK_HOURS),
        "health_regression": int(settings.IMPROVEMENT_COOLDOWN_ROLLBACK_HOURS),
    }
    return max(0, mapping.get(failure_class, 0))


def candidate_failure_history(project_name: str, fingerprint: str, *, limit: int = 50) -> list[Dict[str, Any]]:
    init_database()
    with get_db() as conn:
        rows = conn.execute(
            """SELECT c.id, c.status, c.updated_at, c.cycle_id, o.apply_status, o.score_delta
               FROM improvement_candidates c
               JOIN improvement_cycles y ON y.id = c.cycle_id
               LEFT JOIN improvement_outcomes o ON o.candidate_id = c.id
               WHERE y.project_name = ? AND c.candidate_fingerprint = ?
               ORDER BY COALESCE(c.updated_at, c.created_at) DESC LIMIT ?""",
            (project_name, fingerprint, max(1, min(int(limit), 500))),
        ).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        status = str(item.get("status") or "")
        apply_status = str(item.get("apply_status") or "")
        failure_class = _FAILURE_STATUSES.get(status)
        if apply_status.startswith("rolled_back_health"):
            failure_class = "health_regression"
        elif apply_status.startswith("rolled_back"):
            failure_class = "rollback"
        if failure_class:
            item["failure_class"] = failure_class
            output.append(item)
    return output


def apply_failure_cooldowns_and_risk(project_name: str, candidates: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    output = []
    for raw in candidates:
        item = dict(raw)
        fingerprint = str(item.get("candidate_fingerprint") or "")
        history = candidate_failure_history(project_name, fingerprint, limit=int(settings.IMPROVEMENT_REPEAT_HISTORY_LIMIT)) if fingerprint else []
        active_until: datetime | None = None
        active_class = None
        for row in history:
            occurred = _parse(row.get("updated_at"))
            if not occurred:
                continue
            until = occurred + timedelta(hours=_hours(str(row.get("failure_class") or "")))
            if until > now and (active_until is None or until > active_until):
                active_until, active_class = until, row.get("failure_class")
        base_risk = str(item.get("risk") or "medium").lower()
        risk = base_risk if base_risk in _RISK_LEVELS else "medium"
        severe = sum(1 for row in history if row.get("failure_class") in {"rollback", "health_regression", "governance_failure"})
        prod_samples = int(item.get("production_history_samples") or 0)
        prod_rollbacks = int(item.get("production_rollbacks") or 0)
        prod_failure_rate = float(item.get("production_failure_rate") or 0.0)
        steps = 1 if len(history) >= int(settings.IMPROVEMENT_RISK_ESCALATION_FAILURES) else 0
        if severe >= 2:
            steps = max(steps, 1)
        if prod_rollbacks > 0 or (prod_samples >= 2 and prod_failure_rate >= 0.5):
            steps = max(steps, 1)
        if prod_rollbacks >= 2:
            steps = max(steps, 2)
        idx = min(len(_RISK_LEVELS) - 1, _RISK_LEVELS.index(risk) + steps)
        escalated = _RISK_LEVELS[idx]
        item.update({
            "base_risk": base_risk,
            "risk": escalated,
            "cooldown_until": active_until.isoformat() if active_until else None,
            "cooldown_reason": f"failure_class:{active_class}" if active_until else None,
            "risk_escalation": {
                "failure_samples": len(history),
                "severe_failures": severe,
                "base_risk": base_risk,
                "effective_risk": escalated,
                "escalated": escalated != base_risk,
                "production_history_samples": prod_samples,
                "production_rollbacks": prod_rollbacks,
                "production_failure_rate": round(prod_failure_rate, 4),
                "production_evidence_applied": bool(prod_samples),
            },
        })
        output.append(item)
    output.sort(key=lambda row: (bool(row.get("cooldown_until")), -float(row.get("priority_score") or 0.0)))
    return output
