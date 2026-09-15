"""
Qdrant vector store operations.
"""
import logging
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
from app.config import settings

logger = logging.getLogger(__name__)

# Global client instance
_client = None


def get_client() -> QdrantClient:
    """Get or create Qdrant client."""
    global _client
    if _client is None:
        logger.info(f"Connecting to Qdrant at {settings.QDRANT_HOST}:{settings.QDRANT_PORT}")
        _client = QdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            api_key=settings.QDRANT_API_KEY
        )
    return _client


def ensure_collection(collection_name: str = None) -> bool:
    """Ensure collection exists, create if not."""
    if collection_name is None:
        collection_name = settings.QDRANT_COLLECTION
    
    client = get_client()
    
    try:
        collections = client.get_collections().collections
        exists = any(col.name == collection_name for col in collections)
        
        if not exists:
            logger.info(f"Creating Qdrant collection: {collection_name}")
            client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=settings.EMBEDDING_DIMENSION,
                    distance=Distance.COSINE
                )
            )
        return True
    except Exception as e:
        logger.error(f"Error ensuring collection: {e}")
        return False


def upsert_chunk_vector(
    chunk_id: str,
    vector: List[float],
    metadata: Dict[str, Any],
    collection_name: str = None
) -> str:
    """Insert or update a vector in Qdrant."""
    if collection_name is None:
        collection_name = settings.QDRANT_COLLECTION
    
    client = get_client()
    
    point = PointStruct(
        id=chunk_id,
        vector=vector,
        payload=metadata
    )
    
    client.upsert(
        collection_name=collection_name,
        points=[point]
    )
    
    return chunk_id


def search_vectors(
    query_vector: List[float],
    limit: int = 10,
    score_threshold: float = 0.7,
    filters: Optional[Dict[str, Any]] = None,
    collection_name: str = None
) -> List[Dict[str, Any]]:
    """Search for similar vectors."""
    if collection_name is None:
        collection_name = settings.QDRANT_COLLECTION
    
    client = get_client()
    
    # Build filters if provided
    filter_obj = None
    if filters:
        conditions = []
        if "document_id" in filters:
            conditions.append(
                FieldCondition(
                    key="document_id",
                    match=MatchValue(value=filters["document_id"])
                )
            )
        if "knowledge_base_id" in filters:
            conditions.append(
                FieldCondition(
                    key="knowledge_base_id",
                    match=MatchValue(value=filters["knowledge_base_id"])
                )
            )
        
        if conditions:
            filter_obj = Filter(must=conditions)
    
    results = client.search(
        collection_name=collection_name,
        query_vector=query_vector,
        limit=limit,
        score_threshold=score_threshold,
        query_filter=filter_obj
    )
    
    return [
        {
            "chunk_id": str(hit.id),
            "score": hit.score,
            **hit.payload
        }
        for hit in results
    ]


def get_collection_info(collection_name: str = None) -> Dict[str, Any]:
    """Get collection information."""
    if collection_name is None:
        collection_name = settings.QDRANT_COLLECTION
    
    client = get_client()
    
    try:
        info = client.get_collection(collection_name)
        return {
            "name": collection_name,
            "points_count": info.points_count,
            "vectors_count": info.vectors_count,
            "status": info.status
        }
    except Exception as e:
        logger.error(f"Error getting collection info: {e}")
        return {"error": str(e)}


def delete_document_vectors(document_id: str, collection_name: str = None):
    """Delete all vectors for a document."""
    if collection_name is None:
        collection_name = settings.QDRANT_COLLECTION
    
    client = get_client()
    
    client.delete(
        collection_name=collection_name,
        points_selector=Filter(
            must=[
                FieldCondition(
                    key="document_id",
                    match=MatchValue(value=document_id)
                )
            ]
        )
    )
