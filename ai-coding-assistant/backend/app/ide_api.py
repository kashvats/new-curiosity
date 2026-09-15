"""FastAPI surface for Claude-Code/Cursor-style IDE workflows."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.context_builder import build_ide_context
from app.ide_service import SUPPORTED_MODES, run_ide_session
from app.ide_store import append_ide_event, create_ide_session, get_ide_session, is_terminal_session, list_ide_events, update_ide_session
from app.project_paths import resolve_project_root
from app.test_discovery import discover_project_checks
from app.project_navigation import repository_tree, search_project_text, search_symbols
from app.verified_candidate_store import apply_verified_repair

router = APIRouter(prefix="/ide", tags=["ide"])
_ide_tasks: set[asyncio.Task] = set()


class IDESessionRequest(BaseModel):
    mode: str = "ask"
    task: str
    project_name: str = "default"
    files: List[str] = Field(default_factory=list)
    current_file: str | None = None
    selected_text: str = ""
    diagnostics: List[Dict[str, Any]] = Field(default_factory=list)
    terminal_output: str = ""
    evidence: Dict[str, Any] = Field(default_factory=dict)
    validation_plan: List[Dict[str, Any]] = Field(default_factory=list)
    max_attempts: int | None = None


class ApplySessionRequest(BaseModel):
    confirm: bool = False


def _schedule(session_id: str, payload: Dict[str, Any]) -> None:
    async def runner():
        try:
            await run_ide_session(session_id, payload)
        except Exception:
            # run_ide_session persists the failure and event already.
            pass
    task = asyncio.create_task(runner())
    _ide_tasks.add(task)
    task.add_done_callback(_ide_tasks.discard)


@router.get("/modes")
def list_modes():
    return {"modes": sorted(SUPPORTED_MODES)}


@router.post("/sessions", status_code=202)
async def start_session(req: IDESessionRequest):
    mode = req.mode.lower().strip()
    if mode not in SUPPORTED_MODES:
        raise HTTPException(status_code=400, detail=f"Unsupported mode '{mode}'")
    try:
        resolve_project_root(req.project_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    payload = req.model_dump()
    payload["mode"] = mode
    session = create_ide_session(mode=mode, project_name=req.project_name, task=req.task, request=payload)
    _schedule(session["id"], payload)
    return {"status": "queued", "session_id": session["id"], "mode": mode}


@router.get("/sessions/{session_id}")
def session_status(session_id: str):
    session = get_ide_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="IDE session not found")
    return session


@router.get("/sessions/{session_id}/events")
def session_events(session_id: str, after_seq: int = Query(0, ge=0)):
    if not get_ide_session(session_id):
        raise HTTPException(status_code=404, detail="IDE session not found")
    return {"events": list_ide_events(session_id, after_seq=after_seq)}


@router.get("/sessions/{session_id}/events/stream")
async def stream_session_events(session_id: str, after_seq: int = Query(0, ge=0)):
    if not get_ide_session(session_id):
        raise HTTPException(status_code=404, detail="IDE session not found")

    async def stream():
        cursor = int(after_seq)
        idle_ticks = 0
        while True:
            events = list_ide_events(session_id, after_seq=cursor, limit=200)
            if events:
                idle_ticks = 0
                for event in events:
                    cursor = max(cursor, int(event["seq"]))
                    data = json.dumps(event, ensure_ascii=False, default=str)
                    yield f"id: {event['seq']}\nevent: {event['event_type']}\ndata: {data}\n\n"
            else:
                idle_ticks += 1
            session = get_ide_session(session_id)
            if is_terminal_session(session) and not events:
                yield f"event: end\ndata: {json.dumps({'status': session.get('status'), 'last_seq': cursor})}\n\n"
                break
            if idle_ticks >= 20:
                idle_ticks = 0
                yield ": heartbeat\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.post("/sessions/{session_id}/apply")
def apply_session(session_id: str, req: ApplySessionRequest):
    session = get_ide_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="IDE session not found")
    issue_id = session.get("issue_id")
    if not issue_id:
        raise HTTPException(status_code=400, detail="This IDE session has no verified repair to apply")
    try:
        result = apply_verified_repair(issue_id, confirm=req.confirm)
    except KeyError:
        raise HTTPException(status_code=404, detail="Verified repair not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    append_ide_event(session_id, "apply_finished", stage="apply", message=f"Apply finished with status {result.get('status')}", payload=result)
    update_ide_session(session_id, status=result.get("status", session.get("status", "completed")))
    return result


@router.get("/context")
def inspect_context(project_name: str = "default", current_file: str | None = None):
    try:
        context = build_ide_context(project_name=project_name, current_file=current_file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return context


@router.get("/test-discovery")
def test_discovery(project_name: str = "default"):
    try:
        root = resolve_project_root(project_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return discover_project_checks(root)


@router.get("/tree")
def project_tree(project_name: str = "default"):
    try:
        root = resolve_project_root(project_name)
        return repository_tree(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/code-search")
def code_search(project_name: str = "default", q: str = Query(..., min_length=1)):
    try:
        root = resolve_project_root(project_name)
        return search_project_text(root, q)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/symbols")
def symbols(project_name: str = "default", q: str = ""):
    try:
        root = resolve_project_root(project_name)
        return search_symbols(root, q)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
