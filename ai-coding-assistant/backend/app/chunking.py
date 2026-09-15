"""
Document chunking for RAG.
"""
import uuid
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any
from app.config import settings
from app.database import get_db, get_document_by_id, update_document_chunking

logger = logging.getLogger(__name__)


def chunk_text(text: str, chunk_size: int = None, overlap: int = None) -> List[str]:
    """Split text into overlapping chunks."""
    if chunk_size is None:
        chunk_size = settings.CHUNK_SIZE
    if overlap is None:
        overlap = settings.CHUNK_OVERLAP
    
    if not text or len(text) == 0:
        return []
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        
        # Try to break at sentence or word boundary
        if end < len(text):
            # Look for sentence end
            last_period = chunk.rfind('. ')
            last_newline = chunk.rfind('\n')
            break_point = max(last_period, last_newline)
            
            if break_point > chunk_size * 0.5:  # At least 50% of chunk size
                chunk = chunk[:break_point + 1]
                end = start + break_point + 1
        
        chunks.append(chunk.strip())
        start = end - overlap
    
    return [c for c in chunks if c]  # Filter empty chunks


def process_document_chunks(document_id: str) -> int:
    """Process document into chunks and store in database."""
    doc = get_document_by_id(document_id)
    if not doc:
        raise ValueError(f"Document {document_id} not found")
    
    text = doc.get("extracted_text", "")
    if not text:
        raise ValueError(f"No extracted text for document {document_id}")
    
    logger.info(f"Chunking document {document_id}, text length: {len(text)}")
    
    chunks = chunk_text(text)
    logger.info(f"Created {len(chunks)} chunks")
    
    # Store chunks in database
    now = datetime.now(timezone.utc).isoformat()
    
    with get_db() as conn:
        for i, chunk_str in enumerate(chunks):
            chunk_id = str(uuid.uuid4())
            metadata = {
                "chunk_index": i,
                "total_chunks": len(chunks),
                "document_id": document_id,
                "document_name": doc.get("original_filename") or doc.get("stored_filename", "Unknown")
            }
            
            import hashlib
            normalized_hash = hashlib.sha256(chunk_str.encode("utf-8")).hexdigest()
            conn.execute("""
                INSERT OR IGNORE INTO document_chunks (
                    id, document_id, chunk_index, text, metadata_json, created_at, normalized_text_hash, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
            """, (
                chunk_id,
                document_id,
                i,
                chunk_str,
                str(metadata),  # Store as JSON string
                now,
                normalized_hash
            ))
        
        conn.commit()
    
    # Update document
    update_document_chunking(document_id, len(chunks))
    
    return {"status": "completed", "chunk_count": len(chunks)}
