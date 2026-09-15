"""Deterministic knowledge-gap detection.

This module intentionally begins without an LLM. It surfaces concrete missing or
unhealthy knowledge inputs that can later be handed to a Research Agent.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.database import get_db, init_database


def create_knowledge_gap_report(scope: str = "all") -> Dict[str, Any]:
    init_database()
    gaps: List[Dict[str, Any]] = []
    with get_db() as conn:
        failed_docs = conn.execute(
            """SELECT id, original_filename, status, qdrant_status, error
               FROM documents
               WHERE status IN ('failed','error') OR qdrant_status IN ('failed','partial')
               ORDER BY created_at DESC LIMIT 50"""
        ).fetchall()
        for row in failed_docs:
            gaps.append({
                "type": "document_pipeline_failure",
                "severity": "high" if row["qdrant_status"] == "failed" else "medium",
                "document_id": row["id"],
                "name": row["original_filename"],
                "evidence": row["error"] or f"status={row['status']}, qdrant_status={row['qdrant_status']}",
            })

        unindexed = conn.execute(
            """SELECT id, original_filename, chunk_count, indexed_chunk_count
               FROM documents
               WHERE chunk_count > indexed_chunk_count
               ORDER BY created_at DESC LIMIT 50"""
        ).fetchall()
        for row in unindexed:
            gaps.append({
                "type": "unindexed_knowledge",
                "severity": "medium",
                "document_id": row["id"],
                "name": row["original_filename"],
                "evidence": f"{row['indexed_chunk_count']}/{row['chunk_count']} chunks indexed",
            })

        repeated = conn.execute(
            """SELECT issue_id, failure_signature, COUNT(*) AS attempts
               FROM repair_attempts
               WHERE failure_signature IS NOT NULL AND failure_signature != ''
               GROUP BY issue_id, failure_signature HAVING COUNT(*) >= 2
               ORDER BY attempts DESC LIMIT 30"""
        ).fetchall()
        for row in repeated:
            gaps.append({
                "type": "repeated_repair_failure",
                "severity": "high",
                "issue_id": row["issue_id"],
                "failure_signature": row["failure_signature"],
                "evidence": f"same failure repeated {row['attempts']} times",
            })

        report_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        summary = {
            "total_gaps": len(gaps),
            "high": sum(1 for g in gaps if g.get("severity") == "high"),
            "medium": sum(1 for g in gaps if g.get("severity") == "medium"),
        }
        conn.execute(
            "INSERT INTO knowledge_gap_reports (id, scope, status, gaps_json, summary_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (report_id, scope, "gaps_found" if gaps else "healthy", json.dumps(gaps), json.dumps(summary), created_at),
        )
        conn.commit()
    return {"report_id": report_id, "scope": scope, "status": "gaps_found" if gaps else "healthy", "summary": summary, "gaps": gaps}
