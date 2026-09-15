import uuid
import time
import re
from datetime import datetime, timezone
from app.database import get_db_connection

def redact_and_truncate(text: str, max_length: int) -> str:
    if not text:
        return ""
    text = str(text)
    # Redact obvious secrets
    text = re.sub(r'(?i)(api[_-]?key[\s:=]+)["\'][a-zA-Z0-9_\-]+["\']', r'\1"***REDACTED***"', text)
    text = re.sub(r'(?i)(bearer[\s]+)[a-zA-Z0-9_\-\.]+', r'\1***REDACTED***', text)
    text = re.sub(r'(?i)(password[\s:=]+)["\'][^"\']+["\']', r'\1"***REDACTED***"', text)
    if len(text) > max_length:
        text = text[:max_length] + "... [TRUNCATED]"
    return text

def create_run(tool_name: str, input_summary: str, model: str = None) -> str:
    run_id = str(uuid.uuid4())
    conn = get_db_connection()
    try:
        safe_input = redact_and_truncate(input_summary, 2000)
        conn.execute("""
            INSERT INTO agent_runs (
                id, tool_name, status, input_summary, output_summary,
                error, model, duration_ms, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id, tool_name, "running", safe_input, None,
            None, model, 0, datetime.now(timezone.utc).isoformat()
        ))
        conn.commit()
        return run_id
    finally:
        conn.close()

def complete_run(run_id: str, output_summary: str, status: str = "success"):
    conn = get_db_connection()
    try:
        safe_output = redact_and_truncate(output_summary, 4000)
        # Calculate duration roughly using updated time vs created
        cur = conn.cursor()
        cur.execute("SELECT created_at FROM agent_runs WHERE id = ?", (run_id,))
        row = cur.fetchone()
        
        duration_ms = 0
        if row:
            created_at_dt = datetime.fromisoformat(row["created_at"])
            duration_ms = int((datetime.now(timezone.utc) - created_at_dt).total_seconds() * 1000)

        conn.execute("""
            UPDATE agent_runs 
            SET status = ?, output_summary = ?, duration_ms = ?
            WHERE id = ?
        """, (status, safe_output, duration_ms, run_id))
        conn.commit()
    finally:
        conn.close()

def fail_run(run_id: str, error: str):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT created_at FROM agent_runs WHERE id = ?", (run_id,))
        row = cur.fetchone()
        
        duration_ms = 0
        if row:
            created_at_dt = datetime.fromisoformat(row["created_at"])
            duration_ms = int((datetime.now(timezone.utc) - created_at_dt).total_seconds() * 1000)

        conn.execute("""
            UPDATE agent_runs 
            SET status = ?, error = ?, duration_ms = ?
            WHERE id = ?
        """, ("failed", str(error), duration_ms, run_id))
        conn.commit()
    finally:
        conn.close()

def list_runs(limit: int = 50, offset: int = 0, tool_name: str = None) -> list:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        if tool_name:
            cur.execute("""
                SELECT * FROM agent_runs 
                WHERE tool_name = ?
                ORDER BY created_at DESC LIMIT ? OFFSET ?
            """, (tool_name, limit, offset))
        else:
            cur.execute("""
                SELECT * FROM agent_runs 
                ORDER BY created_at DESC LIMIT ? OFFSET ?
            """, (limit, offset))
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()

def get_run(run_id: str) -> dict:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def delete_run(run_id: str):
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM agent_runs WHERE id = ?", (run_id,))
        conn.commit()
    finally:
        conn.close()

def clear_runs(confirm: bool):
    if not confirm:
        raise ValueError("Must confirm to clear runs")
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM agent_runs")
        conn.commit()
    finally:
        conn.close()
