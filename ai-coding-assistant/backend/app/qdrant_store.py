"""Qdrant vector-store operations with lazy optional dependency loading."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)
_client: Any = None


def _qdrant_types():
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
    except ImportError as exc:
        raise RuntimeError("qdrant-client is not installed; vector storage is unavailable") from exc
    return QdrantClient, Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue


def get_client():
    global _client
    if _client is None:
        QdrantClient, *_ = _qdrant_types()
        logger.info("Connecting to Qdrant at %s:%s", settings.QDRANT_HOST, settings.QDRANT_PORT)
        _client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT, api_key=settings.QDRANT_API_KEY)
    return _client


def ensure_collection(collection_name: str | None = None) -> bool:
    collection_name = collection_name or settings.QDRANT_COLLECTION
    try:
        _, Distance, VectorParams, *_ = _qdrant_types()
        client = get_client()
        collections = client.get_collections().collections
        if not any(col.name == collection_name for col in collections):
            client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=settings.EMBEDDING_DIMENSION, distance=Distance.COSINE),
            )
        return True
    except Exception as exc:
        logger.error("Error ensuring collection %s: %s", collection_name, exc)
        return False


def upsert_chunk_vector(chunk_id: str, vector: List[float], metadata: Dict[str, Any], collection_name: str | None = None) -> str:
    collection_name = collection_name or settings.QDRANT_COLLECTION
    *_, PointStruct, _, _, _ = _qdrant_types()
    get_client().upsert(collection_name=collection_name, points=[PointStruct(id=chunk_id, vector=vector, payload=metadata)])
    return chunk_id


def search_vectors(
    query_vector: List[float],
    limit: int = 10,
    score_threshold: float = 0.7,
    filters: Optional[Dict[str, Any]] = None,
    collection_name: str | None = None,
) -> List[Dict[str, Any]]:
    collection_name = collection_name or settings.QDRANT_COLLECTION
    *_, Filter, FieldCondition, MatchValue = _qdrant_types()
    conditions = []
    for key in ("document_id", "knowledge_base_id"):
        if filters and key in filters and filters[key] is not None:
            conditions.append(FieldCondition(key=key, match=MatchValue(value=filters[key])))
    filter_obj = Filter(must=conditions) if conditions else None
    client = get_client()

    # qdrant-client versions expose either search() or query_points(). Prefer the
    # older, widely-supported search contract when available.
    if hasattr(client, "search"):
        hits = client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=limit,
            score_threshold=score_threshold,
            query_filter=filter_obj,
        )
    else:
        response = client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=limit,
            score_threshold=score_threshold,
            query_filter=filter_obj,
        )
        hits = getattr(response, "points", response)

    return [{"chunk_id": str(hit.id), "score": float(hit.score), **(hit.payload or {})} for hit in hits]


def get_collection_info(collection_name: str | None = None) -> Dict[str, Any]:
    collection_name = collection_name or settings.QDRANT_COLLECTION
    try:
        info = get_client().get_collection(collection_name)
        return {
            "name": collection_name,
            "points_count": getattr(info, "points_count", None),
            "vectors_count": getattr(info, "vectors_count", None),
            "status": str(getattr(info, "status", "unknown")),
        }
    except Exception as exc:
        logger.error("Error getting collection info: %s", exc)
        return {"error": str(exc)}


def delete_document_vectors(document_id: str, collection_name: str | None = None) -> None:
    collection_name = collection_name or settings.QDRANT_COLLECTION
    *_, Filter, FieldCondition, MatchValue = _qdrant_types()
    selector = Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))])
    get_client().delete(collection_name=collection_name, points_selector=selector)
