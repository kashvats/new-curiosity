"""Improvement candidate generation and deterministic prioritization."""
from __future__ import annotations

import uuid
from typing import Any, Dict, Iterable, List

from app.config import settings

_RISK_FACTOR = {"low": 1.0, "medium": 1.8, "high": 4.0, "critical": 8.0}


def _num(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def priority_score(*, benefit: float, confidence: float, urgency: float, risk: str, estimated_cost: float) -> float:
    """benefit × confidence × urgency / (risk × cost), normalized but not capped."""
    risk_factor = _RISK_FACTOR.get(str(risk).lower(), 4.0)
    cost = max(0.25, _num(estimated_cost, 1.0))
    return round(max(0.0, _num(benefit, 0.0)) * max(0.0, _num(confidence, 0.0)) * max(0.0, _num(urgency, 0.0)) / (risk_factor * cost), 6)


def generate_improvement_candidates(snapshot: Dict[str, Any], *, cycle_id: str | None = None) -> List[Dict[str, Any]]:
    """Turn health findings into small, auditable candidate records.

    No LLM is needed here. Findings already carry evidence and a bounded suggested
    action. This makes candidate generation available even when models are offline.
    """
    candidates: list[Dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    max_files = max(1, int(settings.IMPROVEMENT_MAX_FILES))

    for finding in snapshot.get("findings", []):
        if finding.get("actionable") is False:
            continue
        task = str(finding.get("suggested_task") or finding.get("message") or "").strip()
        if not task:
            continue
        likely_files = [str(v) for v in finding.get("likely_files", []) if v][:max_files]
        key = (str(finding.get("code", "generic")), tuple(likely_files))
        if key in seen:
            continue
        seen.add(key)
        risk = str(finding.get("risk", "medium")).lower()
        benefit = _num(finding.get("benefit"), 0.5)
        confidence = _num(finding.get("confidence"), 0.6)
        urgency = _num(finding.get("urgency"), 0.5)
        estimated_cost = _num(finding.get("estimated_cost"), 1.0)
        score = priority_score(
            benefit=benefit, confidence=confidence, urgency=urgency,
            risk=risk, estimated_cost=estimated_cost,
        )
        category = str(finding.get("category") or "generic").strip().lower()
        code = str(finding.get("code") or "generic").strip().lower()
        candidates.append({
            "id": str(uuid.uuid4()),
            "cycle_id": cycle_id,
            "problem": str(finding.get("message", task)),
            "evidence": {
                "health_finding": {
                    "category": finding.get("category"),
                    "severity": finding.get("severity"),
                    "code": finding.get("code"),
                    "evidence": finding.get("evidence", {}),
                },
                "baseline_health_score": snapshot.get("health_score"),
                "baseline_dimensions": snapshot.get("dimensions", {}),
            },
            "proposal": task,
            "risk": risk,
            "benefit": benefit,
            "confidence": confidence,
            "urgency": urgency,
            "estimated_cost": estimated_cost,
            "base_priority_score": score,
            "learning_multiplier": 1.0,
            "history_samples": 0,
            "history_success_rate": 0.0,
            "history_average_score_delta": 0.0,
            "strategy_key": f"{category}:{code}:{risk}",
            "priority_score": score,
            "likely_files": likely_files,
            "validation_plan": list(finding.get("validation_plan") or []),
            "status": "proposed",
        })

    candidates.sort(key=lambda item: (-float(item["priority_score"]), item["risk"], item["problem"]))
    return candidates[: max(1, int(settings.IMPROVEMENT_MAX_CANDIDATES))]


def select_improvement_candidate(
    candidates: Iterable[Dict[str, Any]],
    *,
    allowed_risks: Iterable[str] | None = None,
    min_priority: float | None = None,
) -> Dict[str, Any] | None:
    allowed = {v.strip().lower() for v in (allowed_risks or str(settings.IMPROVEMENT_ALLOWED_RISKS).split(",")) if str(v).strip()}
    threshold = float(settings.IMPROVEMENT_MIN_PRIORITY if min_priority is None else min_priority)
    eligible = [
        item for item in candidates
        if str(item.get("risk", "medium")).lower() in allowed
        and float(item.get("priority_score") or 0.0) >= threshold
    ]
    if not eligible:
        return None
    eligible.sort(key=lambda item: (-float(item.get("priority_score") or 0.0), float(item.get("estimated_cost") or 1.0)))
    return eligible[0]
