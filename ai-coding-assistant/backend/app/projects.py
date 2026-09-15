from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
import os
import uuid
import datetime
from app.config import settings

router = APIRouter(prefix="/projects", tags=["projects"])
@router.get("/available")
def list_available_projects():
    try:
        root = settings.WORKSPACE_ROOT
        projects = []
        if os.path.exists(root):
            for item in os.listdir(root):
                item_path = os.path.join(root, item)
                if os.path.isdir(item_path) and not item.startswith("."):
                    projects.append(item)
        return {"projects": sorted(projects)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/index-codebase")
def trigger_codebase_index():
    from app.codebase_indexing import index_codebase
    try:
        res = index_codebase(settings.WORKSPACE_ROOT)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/architecture/analyze")
async def trigger_architecture_analysis():
    from app.architecture import generate_architecture_map
    try:
        res = await generate_architecture_map(settings.WORKSPACE_ROOT)
        if res.get("status") == "error":
            raise HTTPException(status_code=500, detail=res.get("message"))
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ImpactRequest(BaseModel):
    target_file: str
    proposed_change: str

@router.post("/impact/analyze")
async def trigger_impact_analysis(req: ImpactRequest):
    from app.impact_analysis import analyze_impact
    try:
        res = await analyze_impact(req.target_file, req.proposed_change)
        if res.get("status") == "error":
            raise HTTPException(status_code=500, detail=res.get("message"))
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class AuditRunRequest(BaseModel):
    project_name: str

@router.post("/audit/run")
async def run_audit(req: AuditRunRequest):
    root = settings.WORKSPACE_ROOT
    project_path = os.path.join(root, req.project_name)
    
    # If not found directly, try to find it recursively (e.g. for nested projects)
    if not os.path.exists(project_path) or not os.path.isdir(project_path):
        found = False
        for root_dir, dirs, files in os.walk(root):
            if req.project_name in dirs:
                project_path = os.path.join(root_dir, req.project_name)
                found = True
                break
        
        if not found:
            raise HTTPException(status_code=404, detail=f"Project folder '{req.project_name}' not found in workspace.")
            
    # Trigger the auditor logic
    from app.project_auditor import run_project_audit
    try:
        report = await run_project_audit(project_path, req.project_name)
        if report.get("status") == "error":
            raise HTTPException(status_code=500, detail=report.get("message"))
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/audit/reports")
def get_audit_reports(project_name: str = None):
    from app.database import get_db
    import json
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            if project_name:
                cursor.execute("SELECT id, scope, overall_status, created_at FROM project_audit_reports WHERE scope=? ORDER BY created_at DESC LIMIT 20", (project_name,))
            else:
                cursor.execute("SELECT id, scope, overall_status, created_at FROM project_audit_reports ORDER BY created_at DESC LIMIT 20")
            reports = [dict(row) for row in cursor.fetchall()]
            return {"reports": reports}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class AuditFixRequest(BaseModel):
    project_name: str
    task: str
    likely_files: list[str]

@router.post("/audit/fix")
async def trigger_audit_fix(req: AuditFixRequest):
    from app.coder import draft_code_changes
    try:
        root = settings.WORKSPACE_ROOT
        project_path = os.path.join(root, req.project_name)
        
        # If not found directly, try to find it recursively
        relative_prefix = req.project_name
        if not os.path.exists(project_path) or not os.path.isdir(project_path):
            for root_dir, dirs, files in os.walk(root):
                if req.project_name in dirs:
                    project_path = os.path.join(root_dir, req.project_name)
                    # Get the relative path from WORKSPACE_ROOT
                    relative_prefix = os.path.relpath(project_path, root)
                    break
                    
        adjusted_files = [os.path.join(relative_prefix, f) for f in req.likely_files]
        # Autoregressive Feedback Loop
        history_context = ""
        try:
            import asyncio
            from app.database import get_db
            def _fetch_history():
                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT overall_status, findings_json FROM project_audit_reports WHERE scope=? ORDER BY created_at DESC LIMIT 1", (req.project_name,))
                    return cursor.fetchone()
            row = await asyncio.to_thread(_fetch_history)
            if row:
                history_context = f"\n\n[AUTOREGRESSIVE VULNERABILITY CONTEXT]\nLast Audit Status: {row['overall_status']}\nPast Findings: {row['findings_json']}\nAvoid introducing code that violates these known architectural vulnerabilities."
        except Exception:
            pass

        extra_ctx = f"You are executing a fix generated by the Project Auditor for the project '{req.project_name}'. Make the change directly in the {req.project_name} directory.{history_context}"

        res = await draft_code_changes(
            task=f"AUDITOR FIX TICKET:\n{req.task}\n\nProject Context: {req.project_name}",
            file_paths=adjusted_files,
            extra_context=extra_ctx,
            project_name=req.project_name
        )
        return {"status": "ok", "proposed_changes": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ApplyChangesRequest(BaseModel):
    project_name: str
    task: str
    changes: dict

@router.post("/audit/fix/apply")
def trigger_audit_fix_apply(req: ApplyChangesRequest):
    try:
        root = settings.WORKSPACE_ROOT
        
        # Unwrap nested dict if the frontend sends the whole object
        changes_list = req.changes.get("proposed_changes", [])
        if isinstance(changes_list, dict):
            changes_list = changes_list.get("proposed_changes", [])
            
        for change in changes_list:
            if not isinstance(change, dict):
                continue
                
            action = change.get("action")
            path = change.get("path")
            content = change.get("content")
            
            if not path or not content:
                continue
            
            full_path = os.path.join(root, path)
            # Normalize: strip any leading project_name prefix the LLM may have added
            # so files always land inside the project dir, not the workspace root
            try:
                rel = os.path.relpath(full_path, root)
                # If the relative path starts with project_name, use project_path as base
                parts = rel.replace("\\", "/").split("/")
                if parts[0] == req.project_name:
                    clean_rel = "/".join(parts[1:])
                    full_path = os.path.join(root, req.project_name, clean_rel)
            except ValueError:
                pass  # relpath can fail on Windows with different drives — safe to ignore
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            
            if action in ["modify", "create"]:
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(content)
                    
        # History & Queue Updates
        import uuid
        import json
        from datetime import datetime, timezone
        from app.database import get_db
        
        now = datetime.now(timezone.utc).isoformat()
        
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                # 1. Save History
                cursor.execute(
                    "INSERT INTO audit_fix_history (id, project_name, task, changes_json, created_at) VALUES (?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), req.project_name, req.task, json.dumps(req.changes), now)
                )
                
                # 2. Pop off the queue for the latest report
                cursor.execute(
                    "SELECT id, fix_queue_json FROM project_audit_reports WHERE scope=? ORDER BY created_at DESC LIMIT 1",
                    (req.project_name,)
                )
                row = cursor.fetchone()
                if row:
                    report_id = row["id"]
                    try:
                        queue = json.loads(row["fix_queue_json"])
                        # Filter out the fixed task
                        filtered_queue = [q for q in queue if q.get("task") != req.task]
                        cursor.execute(
                            "UPDATE project_audit_reports SET fix_queue_json = ? WHERE id = ?",
                            (json.dumps(filtered_queue), report_id)
                        )
                    except json.JSONDecodeError:
                        pass
                conn.commit()

                # 3. Invalidate architecture cache for this project so the next
                #    audit triggers a fresh LLM pass instead of returning stale
                #    findings (e.g. "Dockerfile missing" after we just created it).
                try:
                    # architecture_cache rows keyed by component_name (= project folder or sub-folder)
                    cursor.execute(
                        "DELETE FROM architecture_cache WHERE component_name = ? OR component_name LIKE ?",
                        (req.project_name, f"{req.project_name}/%")
                    )
                    deleted_arch = cursor.rowcount
                    # Also wipe the stored audit report for this project so the
                    # auditor re-runs fresh instead of serving a cached report
                    cursor.execute(
                        "DELETE FROM project_audit_reports WHERE scope = ?",
                        (req.project_name,)
                    )
                    deleted_reports = cursor.rowcount
                    conn.commit()
                    if deleted_arch or deleted_reports:
                        print(
                            f"[Cache Invalidation] Project '{req.project_name}': "
                            f"deleted {deleted_arch} architecture_cache row(s) and "
                            f"{deleted_reports} audit report(s). Next audit will be fresh."
                        )
                except Exception as cache_err:
                    # Non-fatal — do not fail the apply if cache cleanup fails
                    print(f"Warning: Cache invalidation failed (non-fatal): {cache_err}")

        except Exception as db_err:
            print(f"Warning: Failed to update audit history/queue: {db_err}")
                    
        return {"status": "ok", "message": "Changes applied successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Phase 5: Session Status API
# ---------------------------------------------------------------------------
import json as _json

@router.get("/audit/fix/session/{session_id}")
def get_session_status(session_id: str):
    """
    Get the live status of a coder session by ID.
    Returns progress stats, which nodes are complete/failed/pending, and the result.
    """
    from app.database import get_db
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM coder_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

        d = dict(row)
        graph = _json.loads(d["graph_json"])
        completed = _json.loads(d["completed_nodes"])
        failed = _json.loads(d["failed_nodes"])
        generated = _json.loads(d["generated_files"])

        total = len(graph)
        n_done = len(completed)
        n_failed = len(failed)
        n_pending = total - n_done - n_failed
        pct = round((n_done / total * 100) if total else 0, 1)

        # Build per-node status for the frontend to render a graph view
        nodes_status = []
        for node in graph:
            nid = node["id"]
            if nid in completed:
                node_status = "complete"
            elif nid in failed:
                node_status = "failed"
            elif nid == d.get("current_node_id"):
                node_status = "running"
            else:
                node_status = "pending"
            nodes_status.append({
                "id": nid,
                "file": node["file"],
                "goal": node.get("goal", ""),
                "depends_on": node.get("depends_on", []),
                "status": node_status,
                "error": failed.get(nid) if nid in failed else None,
                "generated": nid in completed,
            })

        return {
            "session_id": session_id,
            "project_name": d["project_name"],
            "goal": d["goal"],
            "status": d["status"],
            "progress": {
                "total_nodes": total,
                "completed": n_done,
                "failed": n_failed,
                "pending": n_pending,
                "percent_complete": pct,
            },
            "current_node_id": d.get("current_node_id"),
            "nodes": nodes_status,
            "files_generated": list(generated.keys()),
            "import_warnings": _json.loads(d.get("import_warnings") or "[]"),
            "created_at": d["created_at"],
            "updated_at": d["updated_at"],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Phase B: Scoped Impact Analysis — zero LLM, pure reverse import trace
# ---------------------------------------------------------------------------

def _run_scoped_impact(project_root: str, changed_files: list) -> dict:
    """
    For each changed file, find all other files in the project that import it.
    Zero LLM calls — file scanning + regex only.
    Returns { changed_file: [files_that_import_it], ... }
    """
    import re as _re

    affected = {}
    for changed in changed_files:
        norm = changed.replace("\\", "/")
        no_ext = norm[:-3] if norm.endswith(".py") else norm
        parts = no_ext.split("/")

        # Build all possible import name suffixes, e.g.:
        # "ai_tutor/api/views" -> {"views", "api.views", "ai_tutor.api.views"}
        possible_names = set()
        for i in range(len(parts)):
            possible_names.add(".".join(parts[i:]))

        importers = []
        for root, dirs, files in os.walk(project_root):
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".")
                and d not in {"node_modules", "__pycache__", "venv", ".venv", "dist", "build"}
            ]
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                fpath = os.path.join(root, fname)
                rel = os.path.relpath(fpath, project_root).replace("\\", "/")
                if rel in changed_files or rel == changed:
                    continue
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    for name in possible_names:
                        pattern = rf"(from\s+{_re.escape(name)}\s+import|import\s+{_re.escape(name)}(\s|$|,))"
                        if _re.search(pattern, content):
                            importers.append(rel)
                            break
                except Exception:
                    continue

        if importers:
            affected[changed] = importers

    return affected
    
# ---------------------------------------------------------------------------
# Phase C: Hybrid Vulnerability Scanning (Deterministic + AI Triage)
# ---------------------------------------------------------------------------

from pydantic import BaseModel
from typing import Optional

class VulnerabilityScanRequest(BaseModel):
    target_url: Optional[str] = None
    db_url: Optional[str] = None

@router.post("/{project_name}/vulnerability_scan")
async def trigger_vulnerability_scan(project_name: str, payload: VulnerabilityScanRequest, background_tasks: BackgroundTasks):
    """
    Kicks off a hybrid vulnerability scan (Bandit/Docker -> AI Triage) in the background.
    """
    import uuid
    from app.hybrid_scanner import start_hybrid_scan
    
    session_id = str(uuid.uuid4())
    background_tasks.add_task(start_hybrid_scan, session_id, project_name, payload.target_url, payload.db_url)
    
    return {
        "status": "started",
        "session_id": session_id,
        "message": "Hybrid scan started in the background."
    }

@router.get("/vulnerability_scan/{session_id}")
async def get_vulnerability_scan_status(session_id: str):
    """
    Poll the status of an ongoing hybrid vulnerability scan.
    """
    from app.hybrid_scanner import get_scanner_session
    
    session = get_scanner_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found")
        
    return {
        "session_id": session_id,
        "status": session["status"],
        "progress": session["progress"],
        "report": session.get("report")
    }

@router.get("/vulnerability_scan/{session_id}/stream")
async def stream_vulnerability_scan(session_id: str):
    """
    Server-Sent Events (SSE) endpoint for real-time scan progress.
    The client opens ONE persistent connection and receives push events
    the moment the scanner updates — no polling required.
    """
    import asyncio
    import json
    from fastapi.responses import StreamingResponse
    from app.hybrid_scanner import get_scanner_session

    async def event_generator():
        last_progress = None
        # Push updates every 500ms. Client closes the connection when done.
        while True:
            session = get_scanner_session(session_id)
            if not session:
                yield f"event: error\ndata: {json.dumps({'message': 'Session not found'})}\n\n"
                break

            current_progress = session["progress"]
            # Only push if something actually changed — no noise
            if current_progress != last_progress:
                last_progress = current_progress
                yield f"event: progress\ndata: {json.dumps({'progress': current_progress, 'status': session['status']})}\n\n"

            if session["status"] in ("completed", "failed"):
                # Push the final report and close the stream
                yield f"event: done\ndata: {json.dumps({'status': session['status'], 'report': session.get('report')})}\n\n"
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disables Nginx buffering for true real-time delivery
        }
    )


@router.get("/audit/fix/session/{session_id}/impact")
def get_session_impact(session_id: str):
    """
    Scoped impact analysis for a completed coder session.
    Reads generated_files from the session, traces reverse imports across the project.
    Zero LLM — pure file scanning.
    """
    from app.database import get_db
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT project_name, status, generated_files FROM coder_sessions WHERE id = ?",
                (session_id,)
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

        d = dict(row)
        generated = _json.loads(d["generated_files"])
        changed_files = list(generated.keys())

        if not changed_files:
            return {
                "session_id": session_id,
                "status": d["status"],
                "changed_files": [],
                "affected_dependents": {},
                "total_affected": 0,
                "risk_level": "none",
                "summary": "No files were generated by this session."
            }

        project_root = os.path.join(settings.WORKSPACE_ROOT, "projects", d["project_name"])
        if not os.path.isdir(project_root):
            # Fallback: try workspace root directly
            project_root = settings.WORKSPACE_ROOT

        affected = _run_scoped_impact(project_root, changed_files)

        total_affected = sum(len(v) for v in affected.values())
        if total_affected == 0:
            risk_level = "low"
        elif total_affected <= 4:
            risk_level = "medium"
        else:
            risk_level = "high"

        # Build plain summary string
        if total_affected == 0:
            summary = f"{len(changed_files)} file(s) changed. No dependents found — isolated change."
        else:
            summary = (
                f"{len(changed_files)} file(s) changed, "
                f"{total_affected} dependent(s) may be affected."
            )

        return {
            "session_id": session_id,
            "project_name": d["project_name"],
            "status": d["status"],
            "changed_files": changed_files,
            "affected_dependents": affected,
            "total_affected": total_affected,
            "risk_level": risk_level,
            "summary": summary,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/audit/fix/sessions")
def list_sessions(project_name: str = None, limit: int = 20):
    """
    List coder sessions, optionally filtered by project_name.
    Returns newest first with compact progress stats.
    """
    from app.database import get_db
    try:
        with get_db() as conn:
            if project_name:
                rows = conn.execute(
                    """SELECT id, project_name, goal, status, completed_nodes,
                              failed_nodes, graph_json, current_node_id,
                              created_at, updated_at
                       FROM coder_sessions
                       WHERE project_name = ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (project_name, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT id, project_name, goal, status, completed_nodes,
                              failed_nodes, graph_json, current_node_id,
                              created_at, updated_at
                       FROM coder_sessions
                       ORDER BY created_at DESC LIMIT ?""",
                    (limit,)
                ).fetchall()

        sessions = []
        for row in rows:
            d = dict(row)
            total = len(_json.loads(d["graph_json"]))
            done = len(_json.loads(d["completed_nodes"]))
            failed = len(_json.loads(d["failed_nodes"]))
            sessions.append({
                "session_id": d["id"],
                "project_name": d["project_name"],
                "goal": d["goal"][:100],
                "status": d["status"],
                "current_node_id": d.get("current_node_id"),
                "progress": {
                    "total_nodes": total,
                    "completed": done,
                    "failed": failed,
                    "percent_complete": round(done / total * 100 if total else 0, 1),
                },
                "created_at": d["created_at"],
                "updated_at": d["updated_at"],
            })
        return {"sessions": sessions, "count": len(sessions)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ResumeSessionRequest(BaseModel):
    session_id: str

@router.post("/audit/fix/session/resume")
async def resume_session(req: ResumeSessionRequest):
    """
    Resume a failed or partial session from where it left off.
    Reuses the existing graph and completed_nodes — only reruns pending/failed nodes.
    """
    from app.coder import draft_code_changes, _load_session
    from app.database import get_db

    session = _load_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{req.session_id}' not found.")
    if session["status"] == "complete":
        raise HTTPException(status_code=400, detail="Session is already complete.")

    # Reset failed nodes so they get retried, keep completed nodes
    import asyncio
    def _reset_session():
        with get_db() as conn:
            conn.execute(
                "UPDATE coder_sessions SET status='pending', failed_nodes='{}', current_node_id=NULL, updated_at=? WHERE id=?",
                (datetime.datetime.now(datetime.timezone.utc).isoformat(), req.session_id)
            )
            conn.commit()
    await asyncio.to_thread(_reset_session)

    try:
        result = await draft_code_changes(
            task=session["goal"],
            file_paths=[],
            extra_context="",
            project_name=session["project_name"],
            session_id=req.session_id
        )
        return {"status": "ok", "session_id": req.session_id, "proposed_changes": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

