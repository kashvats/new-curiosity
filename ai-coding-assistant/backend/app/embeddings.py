"""Embedding generation with lazy optional sentence-transformers loading."""
from __future__ import annotations

import logging
from typing import Any, List

from app.config import settings

logger = logging.getLogger(__name__)
_model: Any = None


def get_model():
    """Get or load the embedding model only when vector operations are requested."""
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed; vector embeddings are unavailable"
            ) from exc
        logger.info("Loading embedding model: %s", settings.EMBEDDING_MODEL)
        _model = SentenceTransformer(settings.EMBEDDING_MODEL)
    return _model


def get_embedding(text: str) -> List[float]:
    model = get_model()
    embedding = model.encode(text, convert_to_tensor=False)
    return embedding.tolist()


def get_embeddings(texts: List[str]) -> List[List[float]]:
    model = get_model()
    embeddings = model.encode(texts, convert_to_tensor=False, show_progress_bar=True)
    return [emb.tolist() for emb in embeddings]
