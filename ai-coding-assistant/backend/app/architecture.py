"""
Phase 51: Architecture Understanding Engine
"""
import logging
from typing import Dict, Any, List, Tuple

from app.workspace_tools import analyze_project_structure, parse_project_manifest
from app.model_manager import model_manager
from app.config import settings

logger = logging.getLogger(__name__)

import os
import asyncio
import hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from app.database import get_db

async def generate_architecture_map(project_path: str) -> Dict[str, Any]:
    """
    Calls the LLM to generate an architectural map using a Map-Reduce pattern.
    """
    logger.info(f"Generating architecture map for {project_path} using Map-Reduce...")
    
    # Ensure path exists
    if not os.path.exists(project_path) or not os.path.isdir(project_path):
        return {"status": "error", "message": f"Path '{project_path}' does not exist or is not a directory."}
        
    fast_model = getattr(settings, "FAST_MODEL", "qwen2.5:0.5b")
    heavy_model = getattr(settings, "PLANNER_MODEL", "qwen3:4b")

    # ── Parse manifest for factual project profile (zero-LLM) ─────────────────
    try:
        manifest = parse_project_manifest(project_path)
        manifest_header = f"""FACTUAL PROJECT PROFILE (use this, do not guess):
- Language: {manifest['language']} | Framework: {manifest['framework']}
- Services detected: {len(manifest['services'])}
""" + "\n".join(
            f"  * {s['name']}: {s['language']}/{s['framework']} port={s['port']} install='{s['install_cmd']}'"
            for s in manifest["services"]
        ) + f"""
- has_docker={manifest['has_docker']} has_cicd={manifest['has_cicd']} has_tests={manifest['has_tests']} has_readme={manifest['has_readme']}
"""
    except Exception as e:
        logger.warning(f"Manifest parse failed (non-critical): {e}")
        manifest = {"services": []}
        manifest_header = "Manifest: could not be parsed."

    # ── Build the list of directories to scan ────────────────────────────────
    # Always scan the given project_path PLUS any sibling service directories
    # so that frontend/ is visible when backend/ is passed (and vice versa).
    IGNORE_DIRS = {"node_modules", "venv", ".venv", "__pycache__", "build", "dist", ".git", "data", "backups"}
    scan_roots: List[Tuple[str, str]] = []  # (display_name, abs_path)

    # Primary project path — scan its direct children as components
    for item in os.listdir(project_path):
        if item.startswith(".") or item in IGNORE_DIRS:
            continue
        scan_roots.append((item, os.path.join(project_path, item)))

    # Sibling service directories from manifest (e.g. frontend/ next to backend/)
    project_abs = str(Path(project_path).resolve())
    for svc in manifest.get("services", []):
        svc_abs = str(Path(svc["path"]).resolve())
        if svc_abs != project_abs:
            # Add the sibling as a top-level component (its name as the display name)
            sibling_name = svc["name"]
            if not any(name == sibling_name for name, _ in scan_roots):
                scan_roots.append((sibling_name, svc["path"]))
                logger.info(f"Map Phase: Added sibling service '{sibling_name}' to scan scope.")

    # 1. MAP PHASE: Pre-scan all scan_roots and split into cache hits vs. LLM misses
    candidates = []
    sub_architectures = {}  # Use dict to preserve order: item -> md string

    for item, item_path in scan_roots:
        raw_structure = analyze_project_structure(item_path)
        if "Error" in raw_structure or not raw_structure.strip():
            continue
        if len(raw_structure) < 50 and os.path.isdir(item_path):
            continue

        dir_hash = hashlib.sha256(raw_structure.encode("utf-8")).hexdigest()

        with get_db() as conn:
            cached = conn.execute(
                "SELECT sub_architecture_md, updated_at FROM architecture_cache WHERE hash_key = ?",
                (dir_hash,)
            ).fetchone()

        if cached:
            # TTL check: treat entries older than 24h as a cache miss
            try:
                row = dict(cached)
                updated_at = datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00"))
                is_fresh = (datetime.now(timezone.utc) - updated_at) < timedelta(hours=24)
            except Exception:
                is_fresh = False

            if is_fresh:
                logger.info(f"Map Phase: Cache HIT for '{item}'. Bypassing LLM.")
                sub_architectures[item] = f"### Component: {item}\n{dict(cached)['sub_architecture_md'].strip()}\n"
            else:
                logger.info(f"Map Phase: Cache STALE for '{item}'. Queuing LLM refresh.")
                candidates.append((item, raw_structure, dir_hash))
        else:
            candidates.append((item, raw_structure, dir_hash))

    # Fire all cache-miss LLM calls in parallel
    async def _analyze_component(item: str, raw_structure: str, dir_hash: str):
        logger.info(f"Map Phase: Cache MISS for '{item}'. Querying LLM...")

        # Inject up to 50 lines from critical files so the LLM sees real code
        real_code_snippets = ""
        item_abs = next((p for n, p in scan_roots if n == item), None)
        if item_abs and os.path.isdir(item_abs):
            priority_files = [
                "requirements.txt", "package.json", "pyproject.toml",
                "main.py", "app.py", "manage.py", "index.js", "index.ts",
                "app/main.py", "src/index.js", "src/main.jsx", "src/App.jsx"
            ]
            for pf in priority_files:
                fp = os.path.join(item_abs, pf)
                if os.path.isfile(fp):
                    try:
                        lines = open(fp, encoding="utf-8", errors="ignore").readlines()[:50]
                        real_code_snippets += f"\n--- {pf} (first 50 lines) ---\n" + "".join(lines)
                    except Exception:
                        pass

        prompt = f"""You are a software architect analyzing a specific component of a larger project.
Component Name: {item}
File Structure:
{raw_structure}
{real_code_snippets}

Describe what this component is responsible for in 2-3 sentences.
Explicitly identify: language, framework, key files, and entry point.
"""
        try:
            res = await model_manager.generate_completion(
                prompt=prompt,
                model=fast_model,
                temperature=0.1,
                max_tokens=500,
                system_prompt="You are an expert software architect. Be concise."
            )
            sub_md = res.strip()
            with get_db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO architecture_cache (hash_key, component_name, sub_architecture_md, updated_at) VALUES (?, ?, ?, ?)",
                    (dir_hash, item, sub_md, datetime.now(timezone.utc).isoformat())
                )
                conn.commit()
            return item, f"### Component: {item}\n{sub_md}\n"
        except Exception as e:
            logger.warning(f"Map phase failed for '{item}': {e}")
            return item, f"### Component: {item}\n(Analysis failed or timed out)\n"

    if candidates:
        tasks = [_analyze_component(item, raw, h) for item, raw, h in candidates]
        results = []
        chunk_size = 15
        for i in range(0, len(tasks), chunk_size):
            chunk = tasks[i:i + chunk_size]
            chunk_results = await asyncio.gather(*chunk)
            results.extend(chunk_results)
            
        for item, md in results:
            sub_architectures[item] = md
            
    # 2. REDUCE PHASE: Stitch together
    if not sub_architectures:
        return {"status": "error", "message": "Failed to extract any sub-architectures to map."}
        
    logger.info("Reduce Phase: Stitching sub-architectures into Master Map...")
    
    combined_subs = "\n".join(sub_architectures.values())
    reduce_prompt = f"""You are the Master Software Architect.
I have analyzed the individual components of a software project.

{manifest_header}

Here are the component descriptions:

{combined_subs}

Synthesize this into a final Master Architecture Map in Markdown.

REQUIREMENTS:
1. Tech Stack Breakdown: List Languages, Frameworks, Libraries, and Tools using the FACTUAL PROJECT PROFILE above. Be specific (e.g., Python 3.11, FastAPI, React 18, SQLite). Do NOT guess.
2. Core Components: List the 3-5 most critical modules and their single responsibility.
3. System Flow: Explain the overall data flow (how a request moves through these components).
4. Mermaid Graph: Provide a detailed Mermaid graph (`graph TD`) mapping ALL detected services and their relationships. Include frontend, backend, and any databases.

Return ONLY clean Markdown. Include the Mermaid diagram in a ```mermaid code block. No filler text.
"""

    try:
        final_res = await model_manager.generate_completion(
            prompt=reduce_prompt,
            model=heavy_model,
            temperature=0.2,
            max_tokens=4000,
            system_prompt="You are a senior software architect."
        )
        
        logger.info("Successfully generated Master Architecture Map.")
        return {
            "status": "ok",
            "model_used": heavy_model,
            "fast_model_used": fast_model,
            "architecture_map_md": final_res.strip()
        }
        
    except Exception as e:
        logger.error(f"Failed to generate Master Architecture map: {repr(e)}")
        return {"status": "error", "message": repr(e)}
