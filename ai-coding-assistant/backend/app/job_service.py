import asyncio
import uuid
import datetime
import json
import logging
from typing import Optional, Dict, Any, List
from app.database import get_db_connection, insert_pipeline_log
from app.models import JobModel

logger = logging.getLogger(__name__)

JOB_HANDLERS = {}

def register_job_handler(job_type: str):
    """Decorator to register a function as a job handler."""
    def decorator(func):
        JOB_HANDLERS[job_type] = func
        return func
    return decorator

def enqueue_job(job_type: str, payload: Optional[Dict[str, Any]] = None) -> JobModel:
    job_id = str(uuid.uuid4())
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    conn = get_db_connection()
    try:
        conn.execute("""
            INSERT INTO background_jobs (
                id, type, status, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            job_id,
            job_type,
            "queued",
            json.dumps(payload) if payload else None,
            now
        ))
        conn.commit()
        
        return JobModel(
            id=job_id,
            type=job_type,
            status="queued",
            payload=payload,
            created_at=now
        )
    finally:
        conn.close()

def get_job(job_id: str) -> Optional[JobModel]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM background_jobs WHERE id = ?", (job_id,))
        row = cur.fetchone()
        if not row:
            return None
            
        return JobModel(
            id=row["id"],
            type=row["type"],
            status=row["status"],
            payload=json.loads(row["payload_json"]) if row["payload_json"] else None,
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error=row["error"],
            retry_count=row["retry_count"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"]
        )
    finally:
        conn.close()

async def process_next_job():
    conn = get_db_connection()
    try:
        # Get next queued job
        cur = conn.cursor()
        cur.execute("SELECT * FROM background_jobs WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1")
        row = cur.fetchone()
        
        if not row:
            return False
            
        job_id = row["id"]
        job_type = row["type"]
        payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
        
        # Mark as running
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn.execute("UPDATE background_jobs SET status = 'running', started_at = ? WHERE id = ?", (now, job_id))
        conn.commit()
        
        if payload.get("document_id") and job_type.startswith("document."):
            insert_pipeline_log({
                "id": str(uuid.uuid4()),
                "document_id": payload.get("document_id"),
                "stage": job_type,
                "status": "started",
                "message": f"Starting {job_type}",
                "retry_count": row["retry_count"],
                "created_at": now
            })
    finally:
        conn.close()
        
    try:
        # Execute job
        handler = JOB_HANDLERS.get(job_type)
        if not handler:
            raise ValueError(f"No handler registered for job type: {job_type}")
            
        if asyncio.iscoroutinefunction(handler):
            result = await handler(job_id, payload)
        else:
            result = handler(job_id, payload)
            
        # Mark as succeeded
        conn = get_db_connection()
        try:
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            conn.execute(
                "UPDATE background_jobs SET status = 'succeeded', completed_at = ?, result_json = ? WHERE id = ?", 
                (now, json.dumps(result) if result else None, job_id)
            )
            conn.commit()
            
            if payload.get("document_id") and job_type.startswith("document."):
                insert_pipeline_log({
                    "id": str(uuid.uuid4()),
                    "document_id": payload.get("document_id"),
                    "stage": job_type,
                    "status": "success",
                    "message": f"Completed {job_type}",
                    "retry_count": row["retry_count"],
                    "created_at": now
                })
        finally:
            conn.close()
            
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        # Mark as failed or retry
        conn = get_db_connection()
        try:
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            # Fetch retry count
            cur = conn.cursor()
            cur.execute("SELECT retry_count, payload_json FROM background_jobs WHERE id = ?", (job_id,))
            row = cur.fetchone()
            current_retry = row["retry_count"] if row else 0
            payload_json = row["payload_json"] if row else "{}"
            payload_dict = json.loads(payload_json) if payload_json else {}
            
            if current_retry < 3:
                # Re-queue
                logger.info(f"Retrying job {job_id} (attempt {current_retry + 1})")
                conn.execute(
                    "UPDATE background_jobs SET status = 'queued', retry_count = ?, error = ? WHERE id = ?",
                    (current_retry + 1, str(e), job_id)
                )
                if payload_dict.get("document_id") and job_type.startswith("document."):
                    insert_pipeline_log({
                        "id": str(uuid.uuid4()),
                        "document_id": payload_dict.get("document_id"),
                        "stage": job_type,
                        "status": "failed_retry",
                        "message": f"Failed: {str(e)}. Retrying...",
                        "retry_count": current_retry,
                        "created_at": now
                    })
            else:
                conn.execute(
                    "UPDATE background_jobs SET status = 'failed', completed_at = ?, error = ? WHERE id = ?", 
                    (now, str(e), job_id)
                )
                
                if payload_dict.get("document_id") and job_type.startswith("document."):
                    insert_pipeline_log({
                        "id": str(uuid.uuid4()),
                        "document_id": payload_dict.get("document_id"),
                        "stage": job_type,
                        "status": "failed_terminal",
                        "message": f"Terminal failure: {str(e)}",
                        "retry_count": current_retry,
                        "created_at": now
                    })
                
                # Dispatch document.failed event if document_id exists
                if "document_id" in payload_dict:
                    from app.events import dispatch
                    # We can't await dispatch directly here because process_next_job might not be the right place to block
                    # but process_next_job is async so we CAN await it!
                    await dispatch("document.failed", {"document_id": payload_dict["document_id"], "error": str(e), "stage": job_type})
                    
            conn.commit()
        finally:
            conn.close()
            
    return True

async def job_worker_loop():
    logger.info("Starting background job worker loop...")
    while True:
        try:
            processed = await process_next_job()
            if not processed:
                await asyncio.sleep(2) # Poll every 2 seconds if no jobs
            else:
                await asyncio.sleep(0.1) # Small delay to not lock up event loop
        except asyncio.CancelledError:
            logger.info("Job worker loop cancelled")
            break
        except Exception as e:
            logger.error(f"Error in job worker loop: {e}")
            await asyncio.sleep(5)
