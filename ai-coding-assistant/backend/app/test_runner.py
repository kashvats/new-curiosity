import uuid
import shlex
import subprocess
import time
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from app.config import settings
from app.database import get_db_connection
from app.models import TestRunRequest

router = APIRouter(prefix="/tests", tags=["test_runner"])

# Commands defined as argument lists (never strings).
# shell=True is permanently removed. Each entry is a pre-split safe arg list
# that subprocess can execute directly without invoking a shell interpreter.
ALLOWED_COMMANDS = {
    "backend_pytest": {
        "args": ["pytest", "backend"],
        "description": "Run Python backend tests locally."
    },
    "docker_backend_pytest": {
        "args": ["docker", "compose", "exec", "backend", "pytest"],
        "description": "Run backend tests inside Docker."
    },
    "frontend_tests": {
        "args": ["npm", "test", "--prefix", "frontend"],
        "description": "Run frontend test suites locally."
    },
    "docker_frontend_tests": {
        "args": ["docker", "compose", "exec", "frontend", "npm", "test"],
        "description": "Run frontend tests inside Docker."
    }
}

def get_allowed_test_commands():
    return [
        {
            "id": k,
            "command": " ".join(v["args"]),
            "description": v["description"]
        }
        for k, v in ALLOWED_COMMANDS.items()
    ]

def validate_test_command(command_id: str):
    if command_id not in ALLOWED_COMMANDS:
        raise ValueError("Command ID is not in the allowlist.")
    return ALLOWED_COMMANDS[command_id]["args"]

def store_test_run_result(run_id, command_id, command_str, status, stdout, stderr, exit_code, duration_ms):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        created_at = datetime.now(timezone.utc).isoformat()
        cur.execute("""
            INSERT INTO test_runs (id, command_id, command, status, stdout, stderr, exit_code, duration_ms, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (run_id, command_id, command_str, status, stdout, stderr, exit_code, duration_ms, created_at))
        conn.commit()
    finally:
        conn.close()

    try:
        from app.change_timeline import create_timeline_event
        create_timeline_event(
            event_type="test_run",
            title=f"Test Run: {command_id}",
            related_test_run_id=run_id,
            status="success" if exit_code == 0 else "failed"
        )
    except ImportError:
        pass

def run_test_command(command_id: str, confirm: bool):
    if not confirm:
        raise ValueError("confirm must be true")

    args = validate_test_command(command_id)
    command_str = " ".join(args)
    run_id = str(uuid.uuid4())

    start_time = time.time()
    try:
        # shell=False: args is a pre-validated list, never user-supplied strings.
        # This completely eliminates shell injection risk.
        process = subprocess.run(
            args,
            shell=False,
            cwd=settings.workspace_root,
            capture_output=True,
            text=True,
            timeout=120
        )
        duration_ms = int((time.time() - start_time) * 1000)
        status = "completed" if process.returncode == 0 else "failed"
        stdout = process.stdout
        stderr = process.stderr
        exit_code = process.returncode

    except subprocess.TimeoutExpired as e:
        duration_ms = int((time.time() - start_time) * 1000)
        status = "timeout"
        stdout = e.stdout.decode() if e.stdout else ""
        stderr = e.stderr.decode() if e.stderr else "Process timed out after 120 seconds."
        exit_code = -1
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        status = "error"
        stdout = ""
        stderr = str(e)
        exit_code = -2

    store_test_run_result(run_id, command_id, command_str, status, stdout, stderr, exit_code, duration_ms)

    return {
        "status": status,
        "run_id": run_id,
        "command_id": command_id,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "stdout": stdout,
        "stderr": stderr
    }

# Routes below are plain `def` — FastAPI auto-threadpools sync handlers.
# `execute_test_run` calls blocking subprocess, so it stays sync too;
# FastAPI ensures it won't block the event loop.

@router.get("/allowed")
def get_allowed_tests():
    try:
        return {"status": "ok", "commands": get_allowed_test_commands()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/run")
def execute_test_run(req: TestRunRequest):
    try:
        result = run_test_command(req.command_id, req.confirm)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/runs")
def get_test_runs():
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, command_id, command, status, exit_code, duration_ms, created_at "
            "FROM test_runs ORDER BY created_at DESC LIMIT 50"
        )
        return {
            "status": "ok",
            "runs": [
                {
                    "id": r[0], "command_id": r[1], "command": r[2],
                    "status": r[3], "exit_code": r[4],
                    "duration_ms": r[5], "created_at": r[6]
                }
                for r in cur.fetchall()
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.get("/runs/{run_id}")
def get_test_run_details(run_id: str):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, command_id, command, status, stdout, stderr, exit_code, duration_ms, created_at "
            "FROM test_runs WHERE id = ?",
            (run_id,)
        )
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=404, detail="Run not found")
        return {
            "status": "ok",
            "run": {
                "id": r[0], "command_id": r[1], "command": r[2],
                "run_status": r[3], "stdout": r[4], "stderr": r[5],
                "exit_code": r[6], "duration_ms": r[7], "created_at": r[8]
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
