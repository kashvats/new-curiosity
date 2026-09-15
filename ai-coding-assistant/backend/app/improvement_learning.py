"""Outcome-memory statistics and conservative learned candidate re-ranking."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List

from app.config import settings
from app.database import get_db, init_database


def strategy_key(candidate: Dict[str, Any]) -> str:
    finding = (candidate.get("evidence") or {}).get("health_finding") or {}
    category = str(finding.get("category") or "generic").strip().lower()
    code = str(finding.get("code") or "generic").strip().lower()
    risk = str(candidate.get("risk") or "medium").strip().lower()
    return f"{category}:{code}:{risk}"


def strategy_statistics(*, project_name: str | None = None, limit: int | None = None) -> List[Dict[str, Any]]:
    """Aggregate measured apply outcomes by deterministic strategy key."""
    init_database()
    limit = max(1, min(int(limit or settings.IMPROVEMENT_HISTORY_LIMIT), 1000))
    query = """
        SELECT o.apply_status, o.score_delta, o.project_name,
               c.strategy_key, c.risk, c.problem
        FROM improvement_outcomes o
        LEFT JOIN improvement_candidates c ON c.id = o.candidate_id
    """
    args: list[Any] = []
    if project_name:
        query += " WHERE o.project_name = ?"
        args.append(project_name)
    query += " ORDER BY o.created_at DESC LIMIT ?"
    args.append(limit)
    with get_db() as conn:
        rows = conn.execute(query, tuple(args)).fetchall()

    try:
        from app.improvement_production_feedback import production_learning_statistics
        production_stats = {item["strategy_key"]: item for item in production_learning_statistics(project_name=project_name)} if project_name else {}
    except Exception:
        production_stats = {}

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        item = dict(row)
        key = str(item.get("strategy_key") or "unknown:unknown:medium")
        grouped[key].append(item)

    output: list[Dict[str, Any]] = []
    min_samples = max(1, int(settings.IMPROVEMENT_MIN_LEARNING_SAMPLES))
    for key in production_stats:
        grouped.setdefault(key, [])
    for key, items in grouped.items():
        samples = len(items)
        successes = sum(1 for item in items if item.get("apply_status") == "applied" and (item.get("score_delta") is None or float(item.get("score_delta") or 0.0) >= -0.5))
        rollbacks = sum(1 for item in items if str(item.get("apply_status") or "").startswith("rolled_back"))
        deltas = [float(item["score_delta"]) for item in items if item.get("score_delta") is not None]
        avg_delta = round(sum(deltas) / len(deltas), 3) if deltas else 0.0
        # Bayesian smoothing prevents one lucky cycle from dominating ranking.
        smoothed_success = (successes + 2.0) / (samples + 4.0)
        multiplier = 1.0
        if samples >= min_samples:
            delta_term = max(-0.2, min(0.2, avg_delta / 25.0))
            success_term = max(-0.2, min(0.2, (smoothed_success - 0.5) * 0.5))
            rollback_term = min(0.25, rollbacks / max(1, samples) * 0.35)
            multiplier = max(0.6, min(1.4, 1.0 + delta_term + success_term - rollback_term))
        prod = production_stats.get(key) or {"samples":0,"failures":0,"rollbacks":0,"failure_rate":0.0,"production_learning_multiplier":1.0,"risk_signal":"low"}
        production_multiplier = float(prod.get("production_learning_multiplier") or 1.0)
        combined_multiplier = max(0.5, min(1.4, multiplier * production_multiplier))
        output.append({
            "strategy_key": key,
            "samples": samples,
            "successes": successes,
            "rollbacks": rollbacks,
            "success_rate": round(successes / samples, 4) if samples else 0.0,
            "smoothed_success_rate": round(smoothed_success, 4),
            "average_score_delta": avg_delta,
            "learning_multiplier": round(combined_multiplier, 4),
            "local_learning_multiplier": round(multiplier, 4),
            "production_history_samples": int(prod.get("samples") or 0),
            "production_failures": int(prod.get("failures") or 0),
            "production_rollbacks": int(prod.get("rollbacks") or 0),
            "production_failure_rate": float(prod.get("failure_rate") or 0.0),
            "production_learning_multiplier": round(production_multiplier, 4),
            "production_risk_signal": str(prod.get("risk_signal") or "low"),
            "learning_active": samples >= min_samples or int(prod.get("samples") or 0) > 0,
        })
    output.sort(key=lambda item: (-item["samples"], item["strategy_key"]))
    return output


def apply_outcome_learning(project_name: str, candidates: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    stats = {item["strategy_key"]: item for item in strategy_statistics(project_name=project_name)}
    output: list[Dict[str, Any]] = []
    for raw in candidates:
        item = dict(raw)
        key = str(item.get("strategy_key") or strategy_key(item))
        base = float(item.get("base_priority_score") if item.get("base_priority_score") is not None else item.get("priority_score") or 0.0)
        learned = stats.get(key) or {
            "samples": 0, "success_rate": 0.0, "average_score_delta": 0.0,
            "learning_multiplier": 1.0, "learning_active": False,
            "production_history_samples": 0, "production_failure_rate": 0.0,
            "production_rollbacks": 0, "production_learning_multiplier": 1.0,
        }
        multiplier = float(learned.get("learning_multiplier") or 1.0)
        item.update({
            "strategy_key": key,
            "base_priority_score": round(base, 6),
            "learning_multiplier": round(multiplier, 4),
            "history_samples": int(learned.get("samples") or 0),
            "history_success_rate": float(learned.get("success_rate") or 0.0),
            "history_average_score_delta": float(learned.get("average_score_delta") or 0.0),
            "production_history_samples": int(learned.get("production_history_samples") or 0),
            "production_failure_rate": float(learned.get("production_failure_rate") or 0.0),
            "production_rollbacks": int(learned.get("production_rollbacks") or 0),
            "production_learning_multiplier": float(learned.get("production_learning_multiplier") or 1.0),
            "priority_score": round(base * multiplier, 6),
        })
        output.append(item)
    output.sort(key=lambda item: (-float(item.get("priority_score") or 0.0), float(item.get("estimated_cost") or 1.0)))
    return output
