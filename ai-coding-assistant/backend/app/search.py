"""Document indexing and retrieval with Qdrant + SQLite keyword fallback."""
from __future__ import annotations

import ast
import json
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from app.database import (
    get_document_by_id,
    get_document_chunks_for_indexing,
    get_db,
    insert_qdrant_index,
    search_keyword_chunks,
    update_chunk_qdrant_status,
)
from app.models import SearchRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/search", tags=["search"])


def _chunk_content(chunk: Dict[str, Any]) -> str:
    return str(chunk.get("text") or chunk.get("content") or "")


def _metadata(chunk: Dict[str, Any], document: Dict[str, Any]) -> Dict[str, Any]:
    raw = chunk.get("metadata_json")
    meta: Dict[str, Any] = {}
    if isinstance(raw, dict):
        meta.update(raw)
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except Exception:
            try:
                parsed = ast.literal_eval(raw)
            except Exception:
                parsed = {}
        if isinstance(parsed, dict):
            meta.update(parsed)
    meta.update({
        "document_id": chunk.get("document_id"),
        "document_name": document.get("original_filename") or document.get("filename") or "Unknown",
        "chunk_index": int(chunk.get("chunk_index") or 0),
        "content": _chunk_content(chunk),
        "knowledge_base_id": document.get("knowledge_base_id"),
    })
    return meta


def index_document_chunks(document_id: str) -> Dict[str, Any]:
    """Embed and index pending chunks. Safe to call repeatedly."""
    document = get_document_by_id(document_id)
    if not document:
        return {"status": "failed", "message": f"Document {document_id} not found"}

    chunks = get_document_chunks_for_indexing(document_id)
    if not chunks:
        with get_db() as conn:
            indexed = conn.execute(
                "SELECT COUNT(*) FROM document_chunks WHERE document_id = ? AND qdrant_status = 'indexed'",
                (document_id,),
            ).fetchone()[0]
            conn.execute(
                "UPDATE documents SET indexed_chunk_count = ?, qdrant_status = CASE WHEN chunk_count = ? THEN 'indexed' ELSE qdrant_status END WHERE id = ?",
                (indexed, indexed, document_id),
            )
            conn.commit()
        return {"status": "completed", "indexed_chunks": 0, "collection": None, "message": "No pending chunks"}

    try:
        from app.embeddings import get_embeddings
        from app.qdrant_store import ensure_collection, upsert_chunk_vector
    except Exception as exc:
        return {"status": "failed", "message": f"Indexing dependency unavailable: {exc}"}

    from app.config import settings
    if not ensure_collection(settings.QDRANT_COLLECTION):
        return {"status": "failed", "message": "Qdrant collection is unavailable"}

    contents = [_chunk_content(chunk) for chunk in chunks]
    nonempty_positions = [i for i, text in enumerate(contents) if text.strip()]
    if not nonempty_positions:
        return {"status": "failed", "message": "Pending chunks contain no text"}

    try:
        vectors = get_embeddings([contents[i] for i in nonempty_positions])
    except Exception as exc:
        return {"status": "failed", "message": f"Embedding generation failed: {exc}"}

    indexed = 0
    errors: List[Dict[str, Any]] = []
    for pos, vector in zip(nonempty_positions, vectors):
        chunk = chunks[pos]
        try:
            point_id = upsert_chunk_vector(
                str(chunk["id"]), vector, _metadata(chunk, document), collection_name=settings.QDRANT_COLLECTION
            )
            insert_qdrant_index(str(chunk["id"]), str(point_id))
            indexed += 1
        except Exception as exc:
            update_chunk_qdrant_status(str(chunk["id"]), "failed", str(exc))
            errors.append({"chunk_id": str(chunk["id"]), "error": str(exc)})

    with get_db() as conn:
        total_indexed = conn.execute(
            "SELECT COUNT(*) FROM document_chunks WHERE document_id = ? AND qdrant_status = 'indexed'",
            (document_id,),
        ).fetchone()[0]
        total_chunks = conn.execute(
            "SELECT COUNT(*) FROM document_chunks WHERE document_id = ?", (document_id,)
        ).fetchone()[0]
        final_status = "indexed" if total_chunks > 0 and total_indexed == total_chunks else ("partial" if total_indexed else "failed")
        conn.execute(
            "UPDATE documents SET indexed_chunk_count = ?, qdrant_status = ?, embedding_status = ? WHERE id = ?",
            (total_indexed, final_status, "embedded" if total_indexed else "failed", document_id),
        )
        conn.commit()

    return {
        "status": "completed" if not errors else ("partial" if indexed else "failed"),
        "indexed_chunks": indexed,
        "failed_chunks": len(errors),
        "errors": errors[:20],
        "collection": settings.QDRANT_COLLECTION,
    }


def _keyword_fallback(query: str, limit: int, knowledge_base_id: str | None) -> List[Dict[str, Any]]:
    rows = search_keyword_chunks(query, limit=max(limit * 3, limit))
    results = []
    for row in rows:
        if knowledge_base_id:
            doc = get_document_by_id(str(row.get("document_id")))
            if not doc or doc.get("knowledge_base_id") != knowledge_base_id:
                continue
        results.append({
            "chunk_id": str(row.get("id") or row.get("chunk_id")),
            "document_id": str(row.get("document_id")),
            "document_name": row.get("filename") or "Unknown",
            "content": row.get("text") or row.get("content") or "",
            "score": 0.5,
            "chunk_index": int(row.get("chunk_index") or 0),
            "source": "keyword_fallback",
        })
        if len(results) >= limit:
            break
    return results


def search_documents(query: str, *, knowledge_base_id: str | None = None, limit: int = 10, score_threshold: float = 0.7) -> Dict[str, Any]:
    if not query.strip():
        return {"query": query, "results": [], "total_results": 0, "source": "none"}
    try:
        from app.embeddings import get_embedding
        from app.qdrant_store import search_vectors
        vector = get_embedding(query)
        filters = {"knowledge_base_id": knowledge_base_id} if knowledge_base_id else None
        hits = search_vectors(vector, limit=limit, score_threshold=score_threshold, filters=filters)
        results = [{
            "chunk_id": str(hit.get("chunk_id")),
            "document_id": str(hit.get("document_id") or ""),
            "document_name": hit.get("document_name") or "Unknown",
            "content": hit.get("content") or "",
            "score": float(hit.get("score") or 0.0),
            "chunk_index": int(hit.get("chunk_index") or 0),
            "source": "qdrant",
        } for hit in hits]
        if results:
            return {"query": query, "results": results, "total_results": len(results), "source": "qdrant"}
    except Exception as exc:
        logger.warning("Vector search unavailable; falling back to SQLite keyword search: %s", exc)

    results = _keyword_fallback(query, limit, knowledge_base_id)
    return {"query": query, "results": results, "total_results": len(results), "source": "keyword_fallback"}


@router.post("")
def search_api(req: SearchRequest):
    try:
        return search_documents(
            req.query,
            knowledge_base_id=req.knowledge_base_id,
            limit=req.limit,
            score_threshold=req.score_threshold,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
