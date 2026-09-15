"""Async compatibility facade for Qdrant operations.

Older API handlers awaited qdrant_service functions while the low-level store is
synchronous. Keeping the boundary here prevents blocking FastAPI's event loop and
restores the missing import without duplicating vector-store logic.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional


async def delete_document_vectors(document_id: str, collection_name: str | None = None) -> None:
    from app.qdrant_store import delete_document_vectors as _delete
    await asyncio.to_thread(_delete, document_id, collection_name)


async def collection_info(collection_name: str | None = None) -> Dict[str, Any]:
    from app.qdrant_store import get_collection_info
    return await asyncio.to_thread(get_collection_info, collection_name)


async def search_vectors(
    query_vector: List[float],
    *,
    limit: int = 10,
    score_threshold: float = 0.7,
    filters: Optional[Dict[str, Any]] = None,
    collection_name: str | None = None,
) -> List[Dict[str, Any]]:
    from app.qdrant_store import search_vectors as _search
    return await asyncio.to_thread(
        _search,
        query_vector,
        limit,
        score_threshold,
        filters,
        collection_name,
    )
