"""Independent LLM review pass for proposed code changes."""
from __future__ import annotations

import json
from typing import Any, Dict, List

from app.model_manager import model_manager, get_effective_model


async def review_changes(task: str, changes: List[Dict[str, Any]], project_name: str = "", validation: Dict[str, Any] | None = None) -> Dict[str, Any]:
    prompt = (
        "You are the Reviewer Agent. You did not author this patch. Review it conservatively for correctness, "
        "scope, regressions, security, and whether validation proves the requested behavior. Return JSON only: "
        "{approved: bool, risk: 'low|medium|high', findings: [str], required_checks: [[str]], summary: str}.\n\n"
        f"TASK:\n{task}\nPROJECT:\n{project_name}\nCHANGES:\n{json.dumps(changes, ensure_ascii=False)[:30000]}\n"
        f"VALIDATION EVIDENCE:\n{json.dumps(validation or {}, ensure_ascii=False, default=str)[:16000]}"
    )
    raw = await model_manager.generate_completion(prompt, model=get_effective_model("reviewer"), temperature=0.1, expect_json=True)
    try:
        data = json.loads(raw)
    except Exception:
        return {"approved": False, "risk": "high", "findings": ["Reviewer returned invalid JSON"], "required_checks": [], "summary": raw[:1000]}
    data.setdefault("approved", False)
    data.setdefault("risk", "medium")
    data.setdefault("findings", [])
    data.setdefault("required_checks", [])
    return data
