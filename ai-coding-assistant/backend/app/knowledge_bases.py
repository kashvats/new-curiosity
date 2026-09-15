"""
Knowledge base management operations.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from app.database import get_db


def create_knowledge_base(name: str, description: Optional[str] = None) -> Dict[str, Any]:
    """Create a new knowledge base."""
    kb_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    with get_db() as conn:
        conn.execute(
            "INSERT INTO knowledge_bases (id, name, description, created_at) VALUES (?, ?, ?, ?)",
            (kb_id, name, description, now)
        )
        conn.commit()
    
    return {
        "id": kb_id,
        "name": name,
        "description": description,
        "created_at": now
    }


def get_knowledge_base(kb_id: str) -> Optional[Dict[str, Any]]:
    """Get knowledge base by ID."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM knowledge_bases WHERE id = ?", (kb_id,))
        row = cursor.fetchone()
        
        if not row:
            return None
        
        # Get document count
        cursor.execute("SELECT COUNT(*) as count FROM documents WHERE knowledge_base_id = ?", (kb_id,))
        doc_count = cursor.fetchone()["count"]
        
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "document_count": doc_count,
            "created_at": row["created_at"]
        }


def list_knowledge_bases() -> List[Dict[str, Any]]:
    """List all knowledge bases."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM knowledge_bases ORDER BY created_at DESC")
        
        kbs = []
        for row in cursor.fetchall():
            cursor.execute("SELECT COUNT(*) as count FROM documents WHERE knowledge_base_id = ?", (row["id"],))
            doc_count = cursor.fetchone()["count"]
            
            kbs.append({
                "id": row["id"],
                "name": row["name"],
                "description": row["description"],
                "document_count": doc_count,
                "created_at": row["created_at"]
            })
        
        return kbs


def delete_knowledge_base(kb_id: str):
    """Delete a knowledge base and unlink documents."""
    with get_db() as conn:
        # Unlink documents
        conn.execute("UPDATE documents SET knowledge_base_id = NULL WHERE knowledge_base_id = ?", (kb_id,))
        # Delete KB
        conn.execute("DELETE FROM knowledge_bases WHERE id = ?", (kb_id,))
        conn.commit()


def get_document_ids_in_kb(kb_id: str) -> List[str]:
    """Get all document IDs in a knowledge base."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM documents WHERE knowledge_base_id = ?", (kb_id,))
        return [row["id"] for row in cursor.fetchall()]
