"""Code drafting service used by IDE mode, audit fixes, and repair agents."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from app.capabilities import capability_summary
from app.config import settings
from app.database import get_db
from app.model_manager import model_manager, get_effective_model
from app.patch_engine import validate_changes, PatchError

logger = logging.getLogger(__name__)


def _workspace_root() -> Path:
    return Path(settings.WORKSPACE_ROOT).expanduser().resolve()


def _safe_read(path: Path, root: Path) -> str:
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return "<blocked: path outside workspace>"
    if not resolved.is_file():
        return "<missing file>"
    text = resolved.read_text(encoding="utf-8", errors="replace")
    limit = int(settings.MAX_CODE_FILE_CHARS)
    if len(text) > limit:
        half = limit // 2
        text = text[:half] + "\n...<TRUNCATED>...\n" + text[-half:]
    return text


def _resolve_context_path(file_path: str, project_name: str) -> Path:
    root = _workspace_root()
    candidate = (root / file_path).resolve()
    if candidate.exists():
        return candidate
    if project_name and project_name not in {"default", "."}:
        alt = (root / project_name / file_path).resolve()
        if alt.exists():
            return alt
    return candidate


def collect_code_context(file_paths: List[str], project_name: str = "default", project_root: str | None = None) -> List[Dict[str, str]]:
    root = Path(project_root).resolve() if project_root else _workspace_root()
    output: List[Dict[str, str]] = []
    for file_path in file_paths[: int(settings.MAX_CODE_CONTEXT_FILES)]:
        if project_root:
            path = (root / file_path).resolve()
            if not path.exists() and project_name not in {"", ".", "default"} and file_path.replace("\\", "/").startswith(project_name.rstrip("/\\") + "/"):
                stripped = file_path.replace("\\", "/")[len(project_name.rstrip("/\\") + "/"): ]
                path = (root / stripped).resolve()
        else:
            path = _resolve_context_path(file_path, project_name)
        content = _safe_read(path, root)
        rel = os.path.relpath(path, root).replace("\\", "/") if path.is_absolute() else file_path
        output.append({
            "path": rel,
            "content": content,
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest() if not content.startswith("<") else "",
        })
    return output


def _extract_json(raw: str) -> Dict[str, Any]:
    text = raw.strip()
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        text = match.group(1)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Coder returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Coder response must be a JSON object")
    return parsed


def _store_session(session_id: str, project_name: str, task: str, files: List[str], result: Dict[str, Any], status: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    changes = result.get("proposed_changes", []) if isinstance(result, dict) else []
    graph = [
        {"id": f"change-{idx+1}", "file": c.get("path", ""), "goal": c.get("reason", ""), "depends_on": []}
        for idx, c in enumerate(changes)
    ]
    completed = [n["id"] for n in graph] if status == "complete" else []
    with get_db() as conn:
        conn.execute(
            """INSERT INTO coder_sessions
               (id, project_name, goal, graph_json, status, completed_nodes, failed_nodes,
                generated_files, import_warnings, current_node_id, result_json, created_at, updated_at, file_paths_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 status=excluded.status, graph_json=excluded.graph_json,
                 completed_nodes=excluded.completed_nodes, generated_files=excluded.generated_files,
                 result_json=excluded.result_json, updated_at=excluded.updated_at,
                 file_paths_json=excluded.file_paths_json""",
            (
                session_id, project_name, task, json.dumps(graph), status,
                json.dumps(completed), "{}",
                json.dumps({c.get("path", ""): c.get("content", "") for c in changes}),
                json.dumps(result.get("warnings", [])), json.dumps(result), now, now, json.dumps(files),
            ),
        )
        conn.commit()


def _load_session(session_id: str) -> Dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM coder_sessions WHERE id=?", (session_id,)).fetchone()
    if not row:
        return None
    data = dict(row)
    for key in ("graph_json", "completed_nodes", "failed_nodes", "generated_files", "import_warnings", "file_paths_json"):
        try:
            data[key.replace("_json", "")] = json.loads(data.get(key) or "[]")
        except Exception:
            pass
    return data


async def draft_code_changes(
    task: str,
    file_paths: List[str] | None = None,
    extra_context: str = "",
    project_name: str = "default",
    session_id: str | None = None,
    project_root: str | None = None,
) -> Dict[str, Any]:
    file_paths = list(file_paths or [])
    session_id = session_id or str(uuid.uuid4())
    context_files = collect_code_context(file_paths, project_name, project_root)
    caps = capability_summary()

    prompt_parts = [
        "You are the Coder Agent in a bounded software-engineering system.",
        "Return strict JSON only. Never execute commands. Never claim tests passed unless evidence is supplied.",
        "Prefer the smallest correct change. Preserve existing architecture and public contracts.",
        "Only propose create or modify actions in this first implementation slice.",
        "Paths must be relative to the workspace and may not contain '..'.",
        "JSON shape: {\"summary\": str, \"proposed_changes\": [{\"path\": str, \"action\": \"create|modify\", \"reason\": str, \"content\": str, \"expected_sha256\": str|null}], \"validation_plan\": [{\"args\": [str], \"cwd\": str|null, \"purpose\": str}], \"warnings\": [str]}",
        f"CAPABILITIES:\n{json.dumps(caps, default=str)}",
        f"TASK:\n{task}",
    ]
    if extra_context:
        prompt_parts.append(f"EXTRA CONTEXT:\n{extra_context}")
    if context_files:
        rendered = []
        for item in context_files:
            rendered.append(f"--- {item['path']} [sha256={item['sha256']}] ---\n{item['content']}")
        prompt_parts.append("FILES:\n" + "\n\n".join(rendered))

    try:
        raw = await model_manager.generate_completion(
            "\n\n".join(prompt_parts),
            model=get_effective_model("coder"),
            temperature=0.2,
            max_tokens=max(int(settings.DEFAULT_MAX_TOKENS), 4000),
            expect_json=True,
        )
        parsed = _extract_json(raw)
        proposed = parsed.get("proposed_changes", [])
        parsed["proposed_changes"] = validate_changes(proposed)
        parsed.setdefault("validation_plan", [])
        parsed.setdefault("warnings", [])
        parsed.update({"status": "ok", "session_id": session_id, "model": get_effective_model("coder")})
        _store_session(session_id, project_name, task, file_paths, parsed, "complete")
        return parsed
    except (ValueError, PatchError, Exception) as exc:
        logger.exception("Coder failed")
        result = {"status": "error", "session_id": session_id, "message": str(exc), "proposed_changes": []}
        try:
            _store_session(session_id, project_name, task, file_paths, result, "failed")
        except Exception:
            logger.exception("Failed to persist coder session")
        return result
