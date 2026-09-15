from fastapi import APIRouter
from app.database import get_db_connection

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# These are plain `def` routes (not async).
# FastAPI automatically runs sync route handlers in its thread pool executor,
# so they never block the async event loop. Zero extra code needed.

@router.get("/status")
def get_dashboard_status():
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT status, COUNT(*) as count FROM background_jobs GROUP BY status")
        jobs_stats = {row["status"]: row["count"] for row in cur.fetchall()}
        cur.execute("SELECT status, COUNT(*) as count FROM documents GROUP BY status")
        docs_stats = {row["status"]: row["count"] for row in cur.fetchall()}
        cur.execute("SELECT qdrant_status, COUNT(*) as count FROM documents GROUP BY qdrant_status")
        indexing_stats = {row["qdrant_status"]: row["count"] for row in cur.fetchall()}
        cur.execute("SELECT id, type, error, created_at FROM background_jobs WHERE status = 'failed' ORDER BY created_at DESC LIMIT 5")
        recent_failures = [dict(r) for r in cur.fetchall()]
        return {
            "background_jobs": jobs_stats,
            "document_processing": docs_stats,
            "indexing": indexing_stats,
            "recent_failures": recent_failures
        }
    finally:
        conn.close()

@router.get("/jobs")
def get_recent_jobs(limit: int = 10):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, type, status, created_at, started_at, completed_at, retry_count "
            "FROM background_jobs ORDER BY COALESCE(completed_at, started_at, created_at) DESC LIMIT ?",
            (limit,)
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
