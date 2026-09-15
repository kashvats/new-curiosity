"""
Embedding generation using sentence transformers.
"""
import logging
from typing import List
from sentence_transformers import SentenceTransformer
from app.config import settings

logger = logging.getLogger(__name__)

# Global model instance (loaded once)
_model = None


def get_model() -> SentenceTransformer:
    """Get or load the embedding model."""
    global _model
    if _model is None:
        logger.info(f"Loading embedding model: {settings.EMBEDDING_MODEL}")
        _model = SentenceTransformer(settings.EMBEDDING_MODEL)
    return _model


def get_embedding(text: str) -> List[float]:
    """Generate embedding for a single text."""
    model = get_model()
    embedding = model.encode(text, convert_to_tensor=False)
    return embedding.tolist()


def get_embeddings(texts: List[str]) -> List[List[float]]:
    """Generate embeddings for multiple texts."""
    model = get_model()
    embeddings = model.encode(texts, convert_to_tensor=False, show_progress_bar=True)
    return [emb.tolist() for emb in embeddings]
