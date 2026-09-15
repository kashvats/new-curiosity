import os
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException
from app.config import settings
from app.database import get_document_by_hash, insert_document
from app.events import dispatch

router = APIRouter(prefix="/storage", tags=["storage"])

def ensure_upload_dir():
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

async def calculate_hash_and_save(file: UploadFile) -> dict:
    ensure_upload_dir()
    
    doc_id = str(uuid.uuid4())
    stored_filename = f"{doc_id}.pdf"
    file_path = os.path.join(settings.UPLOAD_DIR, stored_filename)
    
    sha256_hash = hashlib.sha256()
    file_size_bytes = 0
    
    # Stream the file content to calculate hash and save to disk
    with open(file_path, "wb") as f:
        while chunk := await file.read(8192):
            sha256_hash.update(chunk)
            f.write(chunk)
            file_size_bytes += len(chunk)
            
    file_hash = sha256_hash.hexdigest()
    
    # Check if duplicate exists
    existing_doc = get_document_by_hash(file_hash)
    if existing_doc:
        # Delete the stored duplicate file
        os.remove(file_path)
        return {
            "status": "duplicate",
            "message": "This PDF already exists.",
            "duplicate_of": {
                "id": existing_doc["id"],
                "original_filename": existing_doc["original_filename"],
                "file_hash": existing_doc["file_hash"]
            }
        }
        
    doc = {
        "id": doc_id,
        "filename": stored_filename,
        "original_filename": file.filename,
        "file_hash": file_hash,
        "mime_type": "application/pdf",
        "file_size": file_size_bytes,
        "status": "uploaded",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    insert_document(doc)
    
    return {
        "status": "uploaded",
        "document": {
            "id": doc["id"],
            "original_filename": doc["original_filename"],
            "filename": doc["filename"],
            "file_hash": doc["file_hash"],
            "file_size": doc["file_size"],
            "created_at": doc["created_at"]
        }
    }

def delete_stored_file(file_path: str):
    if os.path.exists(file_path):
        os.remove(file_path)


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """Upload a document for processing."""
    result = await calculate_hash_and_save(file)
    
    if result["status"] == "uploaded":
        # Trigger document processing pipeline
        await dispatch("document.uploaded", {"document_id": result["document"]["id"]})
    
    return result


@router.get("/documents/{document_id}")
async def get_document(document_id: str):
    """Get document metadata."""
    from app.database import get_document_by_id
    
    doc = get_document_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    return doc


@router.delete("/documents/{document_id}")
def delete_document(document_id: str):
    """Delete a document and its associated data."""
    from app.database import get_document_by_id, get_db
    from app.qdrant_store import delete_document_vectors
    
    doc = get_document_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Delete file
    file_path = Path(settings.UPLOAD_DIR) / doc["filename"]
    if file_path.exists():
        file_path.unlink()
    
    # Delete from Qdrant
    try:
        delete_document_vectors(document_id)
    except Exception as e:
        # Log but don't fail if Qdrant deletion fails
        import logging
        logging.warning(f"Could not delete from Qdrant: {e}")
    
    # Delete from database
    with get_db() as conn:
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        conn.commit()
    
    return {"status": "deleted", "document_id": document_id}
