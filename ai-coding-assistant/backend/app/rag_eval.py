"""Small, reproducible retrieval evaluation runner."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from app.database import get_db, init_database
from app.models import EvalRunRequest
from app.search import search_documents


async def run_eval_set(set_id: str, req: EvalRunRequest) -> Dict[str, Any]:
    init_database()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM rag_eval_sets WHERE id = ?", (set_id,)).fetchone()
    if not row:
        return {"status": "failed", "message": f"Eval set {set_id} not found"}
    try:
        cases = json.loads(row["cases_json"] or "[]")
    except Exception:
        cases = []
    if not isinstance(cases, list) or not cases:
        return {"status": "skipped", "message": "Eval set has no cases"}

    results = []
    hits = 0
    for index, case in enumerate(cases):
        if not isinstance(case, dict) or not str(case.get("query", "")).strip():
            results.append({"case": index, "passed": False, "reason": "invalid_case"})
            continue
        response = search_documents(
            str(case["query"]),
            knowledge_base_id=req.knowledge_base_id or case.get("knowledge_base_id"),
            limit=req.limit,
            score_threshold=req.score_threshold,
        )
        returned = response.get("results", [])
        expected_docs = {str(v) for v in case.get("expected_document_ids", [])}
        expected_terms = [str(v).lower() for v in case.get("expected_terms", [])]
        doc_hit = not expected_docs or any(str(item.get("document_id")) in expected_docs for item in returned)
        term_hit = not expected_terms or any(
            any(term in str(item.get("content", "")).lower() for term in expected_terms) for item in returned
        )
        passed = bool(returned) and doc_hit and term_hit
        hits += int(passed)
        results.append({
            "case": index,
            "query": case["query"],
            "passed": passed,
            "result_count": len(returned),
            "source": response.get("source"),
        })

    score = hits / len(cases)
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO rag_eval_runs
               (id, eval_set_id, status, score, results_json, model, created_at, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, set_id, "completed", score, json.dumps(results), None, now, now),
        )
        conn.commit()
    return {"status": "completed", "run_id": run_id, "score": score, "passed": hits, "total": len(cases), "results": results}
