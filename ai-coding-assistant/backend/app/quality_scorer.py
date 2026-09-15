"""Transparent candidate quality scoring for repair/IDE agent modes."""
from __future__ import annotations

from typing import Any, Dict, Iterable


def score_candidate(
    *,
    validation: Dict[str, Any],
    review: Dict[str, Any],
    security: Dict[str, Any],
    changes: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    changes = list(changes)
    score = 100.0
    reasons = []

    if not validation.get("passed"):
        score -= 60
        reasons.append("machine validation failed")
    if not review.get("approved"):
        score -= 30
        reasons.append("independent reviewer rejected candidate")
    review_risk = str(review.get("risk", "medium")).lower()
    score -= {"medium": 5, "high": 15, "critical": 30}.get(review_risk, 0)

    counts = security.get("counts", {})
    score -= 50 * int(counts.get("critical", 0))
    score -= 25 * int(counts.get("high", 0))
    score -= 5 * int(counts.get("medium", 0))
    if not security.get("approved", True):
        reasons.append("security gate rejected candidate")

    file_count = len(changes)
    changed_bytes = sum(len(str(c.get("content", "")).encode("utf-8")) for c in changes)
    if file_count > 8:
        score -= 5
        reasons.append("large file scope")
    if changed_bytes > 250_000:
        score -= 5
        reasons.append("large patch payload")

    score = max(0.0, min(100.0, score))
    accepted = bool(validation.get("passed") and review.get("approved") and security.get("approved") and score >= 70)
    return {
        "score": round(score, 2),
        "accepted": accepted,
        "reasons": reasons,
        "metrics": {"file_count": file_count, "changed_bytes": changed_bytes},
    }
