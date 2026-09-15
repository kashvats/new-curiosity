"""
Database connection and operations for SQLite.
"""
import sqlite3
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from contextlib import contextmanager
from app.config import settings


def get_db_path() -> str:
    """Get the absolute path to the database file."""
    db_path = Path(settings.DATABASE_PATH)
    if not db_path.is_absolute():
        db_path = Path(__file__).parent.parent / settings.DATABASE_PATH
    return str(db_path)


def get_db_connection() -> sqlite3.Connection:
    """Create a new database connection with row factory."""
    # Increase timeout to 60s and allow multi-threading access
    conn = sqlite3.connect(get_db_path(), timeout=60.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Enable robust concurrency settings for WAL mode to prevent 'database is locked' errors
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=60000;")
    return conn


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = get_db_connection()
    try:
        yield conn
    finally:
        conn.close()


def init_database():
    """Initialize database schema if it doesn't exist."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Documents table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                original_filename TEXT,
                file_hash TEXT UNIQUE,
                file_size INTEGER,
                mime_type TEXT,
                status TEXT DEFAULT 'uploaded',
                qdrant_status TEXT DEFAULT 'not_indexed',
                knowledge_base_id TEXT,
                extracted_text TEXT,
                is_scanned BOOLEAN DEFAULT 0,
                ocr_completed BOOLEAN DEFAULT 0,
                chunk_count INTEGER DEFAULT 0,
                indexed_chunk_count INTEGER DEFAULT 0,
                metadata_json TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT
            )
        """)
        
        # Add source_type to documents if it doesn't exist (Migration for Phase 21)
        try:
            cursor.execute("ALTER TABLE documents ADD COLUMN source_type TEXT DEFAULT 'pdf'")
        except sqlite3.OperationalError:
            pass # Column already exists
            
        # Web Memory Sources table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS web_memory_sources (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                query TEXT NOT NULL,
                title TEXT,
                urls_json TEXT,
                summary TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            )
        """)
        
        # Manual Notes table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS manual_notes (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                tags_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            )
        """)
        
        # Project Audit Reports (Phase 58)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS project_audit_reports (
                id TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                overall_status TEXT NOT NULL,
                summary_json TEXT,
                findings_json TEXT,
                recommendations_json TEXT,
                fix_queue_json TEXT,
                created_at TEXT NOT NULL
            )
        """)
        
        # Audit Fix History table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_fix_history (
                id TEXT PRIMARY KEY,
                project_name TEXT NOT NULL,
                task TEXT NOT NULL,
                changes_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        
        # Coder Sessions table — persistent graph execution state
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS coder_sessions (
                id TEXT PRIMARY KEY,
                project_name TEXT NOT NULL,
                goal TEXT NOT NULL,
                graph_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                completed_nodes TEXT NOT NULL DEFAULT '[]',
                failed_nodes TEXT NOT NULL DEFAULT '{}',
                generated_files TEXT NOT NULL DEFAULT '{}',
                import_warnings TEXT NOT NULL DEFAULT '[]',
                current_node_id TEXT,
                result_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        # Migration: add import_warnings to existing databases that lack it
        try:
            cursor.execute("ALTER TABLE coder_sessions ADD COLUMN import_warnings TEXT NOT NULL DEFAULT '[]'")
        except Exception:
            pass  # Column already exists — safe to ignore
        # Migration: add file_paths_json to existing databases (for session resume)
        try:
            cursor.execute("ALTER TABLE coder_sessions ADD COLUMN file_paths_json TEXT NOT NULL DEFAULT '[]'")
        except Exception:
            pass  # Column already exists — safe to ignore
        

        # Document chunks table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS document_chunks (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                metadata_json TEXT,
                qdrant_status TEXT DEFAULT 'pending',
                qdrant_point_id TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            )
        """)
        
        # Official Docs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS official_docs (
                technology TEXT PRIMARY KEY,
                source_url TEXT NOT NULL,
                version TEXT NOT NULL,
                chunk_count INTEGER DEFAULT 0,
                last_updated TEXT NOT NULL
            )
        """)
        
        # Background jobs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS background_jobs (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                status TEXT DEFAULT 'queued',
                payload_json TEXT,
                result_json TEXT,
                error TEXT,
                retry_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT
            )
        """)
        
        # Pipeline logs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_logs (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT,
                retry_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            )
        """)
        
        # Knowledge bases table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_bases (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                created_at TEXT NOT NULL
            )
        """)
        
        # Run history table (for test execution tracking)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS run_history (
                id TEXT PRIMARY KEY,
                run_type TEXT NOT NULL,
                status TEXT DEFAULT 'started',
                request_json TEXT,
                response_json TEXT,
                error TEXT,
                duration_ms INTEGER,
                created_at TEXT NOT NULL,
                completed_at TEXT
            )
        """)

        # Error Memory table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS error_memory (
                id TEXT PRIMARY KEY,
                project_path TEXT NOT NULL,
                command TEXT NOT NULL,
                error_output TEXT NOT NULL,
                successful_fix TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        
        # Chat sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                title TEXT,
                document_id TEXT,
                knowledge_base_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Chat messages table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                sources_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
            )
        """)
        
        # Create indexes for common queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_documents_kb ON documents(knowledge_base_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chunks_document ON document_chunks(document_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON background_jobs(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_type ON background_jobs(type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pipeline_document ON pipeline_logs(document_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id)")
        # Architecture cache table (Map-Reduce semantic cache)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS architecture_cache (
                hash_key TEXT PRIMARY KEY,
                component_name TEXT,
                sub_architecture_md TEXT,
                updated_at TEXT
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_arch_cache_component ON architecture_cache(component_name)")
        
        # Backward-compatible migration: add arch_hash to audit reports if not present
        try:
            cursor.execute("ALTER TABLE project_audit_reports ADD COLUMN arch_hash TEXT")
        except Exception:
            pass  # Column already exists
        
        conn.commit()
    finally:
        conn.close()


# Document operations
def get_document_by_id(document_id: str) -> Optional[Dict[str, Any]]:
    """Get document by ID."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE id = ?", (document_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_document_by_hash(file_hash: str) -> Optional[Dict[str, Any]]:
    """Get document by file hash."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE file_hash = ?", (file_hash,))
        row = cursor.fetchone()
        return dict(row) if row else None


def insert_document(doc: Dict[str, Any]):
    """Insert a new document."""
    with get_db() as conn:
        columns = ", ".join(doc.keys())
        placeholders = ", ".join(["?" for _ in doc])
        conn.execute(
            f"INSERT INTO documents ({columns}) VALUES ({placeholders})",
            tuple(doc.values())
        )
        conn.commit()


def update_document_status(document_id: str, status: str, error: Optional[str] = None):
    """Update document status."""
    with get_db() as conn:
        if error:
            conn.execute(
                "UPDATE documents SET status = ?, error = ? WHERE id = ?",
                (status, error, document_id)
            )
        else:
            if status == "indexed":
                conn.execute(
                    "UPDATE documents SET status = ?, embedding_status = 'embedded', qdrant_status = 'indexed' WHERE id = ?",
                    (status, document_id)
                )
            else:
                conn.execute(
                    "UPDATE documents SET status = ? WHERE id = ?",
                    (status, document_id)
                )
        conn.commit()


def update_document_chunking(document_id: str, chunk_count: int):
    """Update document chunk count."""
    with get_db() as conn:
        conn.execute(
            "UPDATE documents SET chunk_count = ?, chunking_status = 'chunked' WHERE id = ?",
            (chunk_count, document_id)
        )
        conn.commit()


def get_document_chunks_for_indexing(document_id: str) -> List[Dict[str, Any]]:
    """Get all chunks for a document that need indexing."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM document_chunks WHERE document_id = ? AND qdrant_status IN ('pending', 'not_started') ORDER BY chunk_index",
            (document_id,)
        )
        return [dict(row) for row in cursor.fetchall()]


def insert_qdrant_index(chunk_id: str, point_id: str):
    """Mark chunk as indexed in Qdrant."""
    with get_db() as conn:
        from datetime import datetime, timezone
        conn.execute(
            "UPDATE document_chunks SET qdrant_status = 'indexed', qdrant_indexed_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), chunk_id)
        )
        conn.commit()


def update_chunk_qdrant_status(chunk_id: str, status: str, error: Optional[str] = None):
    """Update chunk qdrant status."""
    with get_db() as conn:
        conn.execute(
            "UPDATE document_chunks SET qdrant_status = ?, qdrant_error = ? WHERE id = ?",
            (status, error, chunk_id)
        )
        conn.commit()


def get_qdrant_stats() -> Dict[str, int]:
    """Get Qdrant indexing statistics."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT qdrant_status, COUNT(*) as count FROM document_chunks GROUP BY qdrant_status")
        return {row["qdrant_status"]: row["count"] for row in cursor.fetchall()}


def get_document_qdrant_errors(document_id: str) -> List[Dict[str, Any]]:
    """Get Qdrant errors for a document."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM document_chunks WHERE document_id = ? AND qdrant_status = 'failed'",
            (document_id,)
        )
        return [dict(row) for row in cursor.fetchall()]


def search_keyword_chunks(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Simple keyword search in chunks (fallback when Qdrant is unavailable)."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT dc.*, dc.id as chunk_id, d.original_filename as filename 
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE dc.text LIKE ?
            ORDER BY dc.chunk_index
            LIMIT ?
            """,
            (f"%{query}%", limit)
        )
        return [dict(row) for row in cursor.fetchall()]


# Pipeline logs
def insert_pipeline_log(log: Dict[str, Any]):
    """Insert a pipeline log entry."""
    with get_db() as conn:
        columns = ", ".join(log.keys())
        placeholders = ", ".join(["?" for _ in log])
        conn.execute(
            f"INSERT INTO pipeline_logs ({columns}) VALUES ({placeholders})",
            tuple(log.values())
        )
        conn.commit()


def get_document_ids_in_kb(kb_id: str) -> List[str]:
    """Get all document IDs in a knowledge base."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM documents WHERE knowledge_base_id = ?", (kb_id,))
        return [row["id"] for row in cursor.fetchall()]
