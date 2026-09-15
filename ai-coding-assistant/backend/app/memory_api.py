import asyncio
import uuid
import json
import os
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from app.config import settings, get_data_path
from app.database import get_db_connection, insert_document

router = APIRouter(prefix="/memory", tags=["memory"])

class WebSummaryRequest(BaseModel):
    query: str
    title: Optional[str] = None
    summary: str
    urls: List[str] = []
    knowledge_base_id: Optional[str] = None
    create_job: bool = False

@router.post("/web-summary")
def save_web_summary(req: WebSummaryRequest):
    try:
        # Validation
        if not req.query.strip():
            raise HTTPException(status_code=400, detail="Query is required")
        if not req.summary.strip():
            raise HTTPException(status_code=400, detail="Summary is required")
        if len(req.summary) > 20000:
            raise HTTPException(status_code=400, detail="Summary exceeds 20000 characters")
        if len(req.urls) > 20:
            raise HTTPException(status_code=400, detail="Maximum 20 URLs allowed")
        
        for u in req.urls:
            if not u.startswith("http://") and not u.startswith("https://"):
                raise HTTPException(status_code=400, detail=f"Invalid URL schema: {u}")
                
        doc_id = str(uuid.uuid4())
        mem_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        title = req.title or f"Web Search: {req.query}"
        
        # 1. Save text file under /data/web_summaries
        web_summaries_dir = str(get_data_path("web_summaries"))
        os.makedirs(web_summaries_dir, exist_ok=True)
        
        raw_path = os.path.join(web_summaries_dir, f"{doc_id}.txt")
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(f"Query: {req.query}\n")
            f.write(f"Sources: {', '.join(req.urls)}\n\n")
            f.write(req.summary)
            
        # 2. Create extracted JSON under /data/extracted
        extracted_dir = str(get_data_path("extracted"))
        os.makedirs(extracted_dir, exist_ok=True)
        
        extracted_path = os.path.join(extracted_dir, f"{doc_id}.json")
        extracted_data = {
            "document_id": doc_id,
            "total_pages": 1,
            "pages": [
                {
                    "page_number": 1,
                    "text": f"Query: {req.query}\nSources: {', '.join(req.urls)}\n\n{req.summary}"
                }
            ]
        }
        with open(extracted_path, "w", encoding="utf-8") as f:
            json.dump(extracted_data, f)
            
        # 3. Create document record
        doc_record = {
            "id": doc_id,
            "stored_filename": f"{doc_id}.txt",
            "file_path": str(raw_path),
            "original_filename": title,
            "file_hash": doc_id, # mock hash
            "file_size_bytes": len(req.summary),
            "mime_type": "text/plain",
            "status": "uploaded",
            "qdrant_status": "not_started",
            "knowledge_base_id": req.knowledge_base_id,
            "extracted_text": req.summary,
            "is_likely_scanned": 0,
            "ocr_status": "not_started",
            "chunk_count": 0,
            "indexed_chunk_count": 0,
            "created_at": now,
            "source_type": "web_summary",
            "extraction_status": "extracted",
            "extracted_path": str(extracted_path),
            "extracted_at": now,
            "chunking_status": "not_started",
            "embedding_status": "not_started",
            "project_id": "default"
        }
        insert_document(doc_record)
        
        # 4. Create web_memory_sources record
        conn = get_db_connection()
        try:
            conn.execute("""
                INSERT INTO web_memory_sources (
                    id, document_id, query, title, urls_json, summary, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (mem_id, doc_id, req.query, title, json.dumps(req.urls), req.summary, now))
            conn.commit()
        finally:
            conn.close()
            
        # 5. Create job if requested
        job_id = None
        if req.create_job:
            from app.job_service import enqueue_job
            job_id = enqueue_job("pipeline", {"document_id": doc_id})
            
        return {
            "status": "saved",
            "document_id": doc_id,
            "source_type": "web_summary",
            "job_id": job_id
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


class ManualNoteRequest(BaseModel):
    title: str
    content: str
    tags: list[str] = []
    knowledge_base_id: str | None = None
    create_job: bool = False

@router.post("/manual-note")
def save_manual_note(req: ManualNoteRequest):
    try:
        # Validation
        if not req.title.strip():
            raise HTTPException(status_code=400, detail="Title is required")
        if len(req.title) > 200:
            raise HTTPException(status_code=400, detail="Title exceeds 200 characters")
        if not req.content.strip():
            raise HTTPException(status_code=400, detail="Content is required")
        if len(req.content) > 50000:
            raise HTTPException(status_code=400, detail="Content exceeds 50000 characters")
        if len(req.tags) > 20:
            raise HTTPException(status_code=400, detail="Maximum 20 tags allowed")
        for tag in req.tags:
            if len(tag) > 50:
                raise HTTPException(status_code=400, detail=f"Tag '{tag}' exceeds 50 characters")

        doc_id = str(uuid.uuid4())
        note_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        
        # 1. Save JSON note under /data/manual_notes
        notes_dir = str(get_data_path("manual_notes"))
        os.makedirs(notes_dir, exist_ok=True)
        
        raw_path = os.path.join(notes_dir, f"{doc_id}.json")
        note_data = {
            "document_id": doc_id,
            "title": req.title,
            "content": req.content,
            "tags": req.tags,
            "created_at": now,
            "updated_at": now
        }
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(note_data, f)
            
        # 2. Create extracted JSON under /data/extracted
        extracted_dir = str(get_data_path("extracted"))
        os.makedirs(extracted_dir, exist_ok=True)
        
        extracted_path = os.path.join(extracted_dir, f"{doc_id}.json")
        tags_str = ", ".join(req.tags) if req.tags else "None"
        extracted_data = {
            "document_id": doc_id,
            "original_filename": f"Manual Note - {req.title}",
            "page_count": 1,
            "pages": [
                {
                    "page_number": 1,
                    "text": f"{req.title}\n\n{req.content}\n\nTags: {tags_str}"
                }
            ],
            "extracted_at": now
        }
        with open(extracted_path, "w", encoding="utf-8") as f:
            json.dump(extracted_data, f)
            
        # 3. Create document record
        doc_record = {
            "id": doc_id,
            "stored_filename": f"{doc_id}.json",
            "file_path": str(raw_path),
            "original_filename": f"Manual Note - {req.title}",
            "file_hash": doc_id,
            "file_size_bytes": len(req.content),
            "mime_type": "application/json",
            "status": "uploaded",
            "qdrant_status": "not_started",
            "knowledge_base_id": req.knowledge_base_id,
            "extracted_text": req.content,
            "is_likely_scanned": 0,
            "ocr_status": "not_started",
            "chunk_count": 0,
            "indexed_chunk_count": 0,
            "created_at": now,
            "source_type": "manual_note",
            "extraction_status": "extracted",
            "extracted_path": str(extracted_path),
            "extracted_at": now,
            "chunking_status": "not_started",
            "embedding_status": "not_started",
            "project_id": "default"
        }
        insert_document(doc_record)
        
        # 4. Create manual_notes record
        conn = get_db_connection()
        try:
            conn.execute("""
                INSERT INTO manual_notes (
                    id, document_id, title, content, tags_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (note_id, doc_id, req.title, req.content, json.dumps(req.tags), now, now))
            conn.commit()
        finally:
            conn.close()
            
        # 5. Create job if requested
        job_id = None
        if req.create_job:
            from app.job_service import enqueue_job
            job_id = enqueue_job("pipeline", {"document_id": doc_id})
            
        return {
            "status": "saved",
            "document_id": doc_id,
            "source_type": "manual_note",
            "job_id": job_id
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}

@router.get("/manual-notes")
def list_manual_notes():
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM manual_notes ORDER BY created_at DESC")
        notes = [dict(r) for r in cur.fetchall()]
        for n in notes:
            n["tags"] = json.loads(n.get("tags_json") or "[]")
        return {"notes": notes}
    finally:
        conn.close()

@router.get("/manual-notes/{note_id}")
def get_manual_note(note_id: str):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM manual_notes WHERE id = ?", (note_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Note not found")
        note = dict(row)
        note["tags"] = json.loads(note.get("tags_json") or "[]")
        return note
    finally:
        conn.close()

class ManualNoteUpdateRequest(BaseModel):
    title: str
    content: str
    tags: list[str] = []

@router.put("/manual-notes/{note_id}")
def update_manual_note(note_id: str, req: ManualNoteUpdateRequest):
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT document_id FROM manual_notes WHERE id = ?", (note_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Note not found")
            doc_id = row["document_id"]
            
            # 1. Update manual_notes
            cur.execute("""
                UPDATE manual_notes
                SET title = ?, content = ?, tags_json = ?, updated_at = ?
                WHERE id = ?
            """, (req.title, req.content, json.dumps(req.tags), now, note_id))
            
            # 2. Update documents table (reset statuses)
            cur.execute("""
                UPDATE documents
                SET original_filename = ?,
                    extracted_text = ?,
                    file_size_bytes = ?,
                    chunking_status = 'not_started',
                    embedding_status = 'not_started',
                    qdrant_status = 'not_started'
                WHERE id = ?
            """, (f"Manual Note - {req.title}", req.content, len(req.content), doc_id))
            
            conn.commit()
            
            # 3. Update JSON files
            notes_dir = str(get_data_path("manual_notes"))
            raw_path = os.path.join(notes_dir, f"{doc_id}.json")
            if os.path.exists(raw_path):
                with open(raw_path, "r", encoding="utf-8") as f:
                    note_data = json.load(f)
                note_data.update({
                    "title": req.title,
                    "content": req.content,
                    "tags": req.tags,
                    "updated_at": now
                })
                with open(raw_path, "w", encoding="utf-8") as f:
                    json.dump(note_data, f)
                    
            extracted_dir = str(get_data_path("extracted"))
            extracted_path = os.path.join(extracted_dir, f"{doc_id}.json")
            tags_str = ", ".join(req.tags) if req.tags else "None"
            if os.path.exists(extracted_path):
                with open(extracted_path, "r", encoding="utf-8") as f:
                    extracted_data = json.load(f)
                extracted_data["original_filename"] = f"Manual Note - {req.title}"
                extracted_data["pages"][0]["text"] = f"{req.title}\n\n{req.content}\n\nTags: {tags_str}"
                extracted_data["extracted_at"] = now
                with open(extracted_path, "w", encoding="utf-8") as f:
                    json.dump(extracted_data, f)
                    
            return {"status": "updated", "message": "Note updated. Re-chunk and re-index required."}
        finally:
            conn.close()
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}

@router.delete("/manual-notes/{note_id}")
async def delete_manual_note(note_id: str):
    def _fetch_and_delete_note():
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT document_id FROM manual_notes WHERE id = ?", (note_id,))
            row = cur.fetchone()
            if not row:
                return None
            doc_id = row["document_id"]
            # Delete from manual_notes
            cur.execute("DELETE FROM manual_notes WHERE id = ?", (note_id,))
            conn.commit()
            return doc_id
        finally:
            conn.close()

    doc_id = await asyncio.to_thread(_fetch_and_delete_note)
    if doc_id is None:
        raise HTTPException(status_code=404, detail="Note not found")

    try:
        from app.qdrant_service import delete_document_vectors
        await delete_document_vectors(doc_id)
    except Exception as e:
        print(f"Failed to delete Qdrant vectors: {e}")

    def _delete_remaining_records():
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM document_chunks WHERE document_id = ?", (doc_id,))
            conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
            conn.commit()
        finally:
            conn.close()

    await asyncio.to_thread(_delete_remaining_records)
        
    # Delete files
    notes_dir = str(get_data_path("manual_notes"))
    raw_path = os.path.join(notes_dir, f"{doc_id}.json")
    if os.path.exists(raw_path):
        os.remove(raw_path)
        
    extracted_dir = str(get_data_path("extracted"))
    extracted_path = os.path.join(extracted_dir, f"{doc_id}.json")
    if os.path.exists(extracted_path):
        os.remove(extracted_path)
        
    return {"status": "deleted"}
