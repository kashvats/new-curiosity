import os
import json
import uuid
import asyncio
import subprocess
import logging
from typing import Dict, Any, List
from pathlib import Path

from app.config import settings
from app.model_manager import get_effective_model, model_manager
from app.codebase_indexing import build_project_symbol_index

logger = logging.getLogger(__name__)

# Simple in-memory status store for polling
# Format: { session_id: { "status": "running|completed|failed", "progress": "string", "report": dict } }
_SCANNER_SESSIONS: Dict[str, Dict[str, Any]] = {}

def get_scanner_session(session_id: str) -> Dict[str, Any]:
    return _SCANNER_SESSIONS.get(session_id)

async def _run_bandit_scan(project_path: str) -> List[Dict]:
    """Runs Bandit on the project path and returns the raw findings."""
    logger.info(f"Running deterministic SAST (Bandit) on {project_path}")
    
    # We run bandit inside an ephemeral Docker container for security/isolation.
    # We mount the project path to /src inside the container.
    # Using the official python image, pip installing bandit silently, and running it.
    
    # Resolve absolute path to mount
    abs_project_path = os.path.abspath(project_path)
    
    cmd = [
        "docker", "run", "--rm", 
        "-v", f"{abs_project_path}:/src", 
        "python:3.10-slim", 
        "sh", "-c", "pip install -q bandit && bandit -r /src -f json -ll"
    ]
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            # Hard 5-minute timeout. On expiry we kill the OS process (not just the coroutine)
            # to prevent zombie processes leaking memory on the host machine.
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
        except asyncio.TimeoutError:
            logger.error("Bandit scan timed out after 300s. Killing process.")
            process.kill()
            await process.wait()
            return []
        
        # Bandit returns non-zero exit code if it finds issues, so we just parse stdout
        try:
            output = json.loads(stdout.decode())
            results = output.get("results", [])
            # Convert absolute container paths back to relative project paths
            for r in results:
                if "filename" in r:
                    r["filename"] = r["filename"].replace("/src/", "").replace("/src", "")
            return results
        except json.JSONDecodeError:
            logger.error(f"Bandit output invalid JSON. Stderr: {stderr.decode()}")
            return []
            
    except Exception as e:
        logger.error(f"Failed to run Bandit: {e}")
        return []

async def _run_semgrep_scan(project_path: str) -> List[Dict]:
    """Runs Semgrep on the project path and returns the raw findings."""
    logger.info(f"Running deterministic SAST (Semgrep) on {project_path}")
    
    abs_project_path = os.path.abspath(project_path)
    cmd = [
        "docker", "run", "--rm", 
        "-v", f"{abs_project_path}:/src", 
        "returntocorp/semgrep", 
        "semgrep", "scan", "--config", "auto", "--json", "/src"
    ]
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
        except asyncio.TimeoutError:
            logger.error("Semgrep scan timed out after 300s. Killing process.")
            process.kill()
            await process.wait()
            return []
        
        try:
            output = json.loads(stdout.decode())
            results = output.get("results", [])
            mapped_results = []
            
            for r in results:
                # Map Semgrep format to our unified dictionary
                filepath = r.get("path", "")
                filepath = filepath.replace("/src/", "").replace("/src", "")
                
                mapped_results.append({
                    "filename": filepath,
                    "line_number": r.get("start", {}).get("line", 0),
                    "test_name": r.get("check_id", "Semgrep Rule"),
                    "issue_severity": r.get("extra", {}).get("severity", "MEDIUM"),
                    "issue_text": r.get("extra", {}).get("message", "No message")
                })
            return mapped_results
        except json.JSONDecodeError:
            logger.error(f"Semgrep output invalid JSON. Stderr: {stderr.decode()}")
            return []
            
    except Exception as e:
        logger.error(f"Failed to run Semgrep: {e}")
        return []

async def _triage_with_llm(raw_findings: List[Dict], project_path: str) -> Dict[str, Any]:
    """Feeds the raw deterministic findings into the LLM for intelligent triage."""
    if not raw_findings:
        return {
            "summary": "No vulnerabilities found during static analysis.",
            "vulnerabilities": []
        }
        
    # Get project context
    try:
        sym = build_project_symbol_index(project_path)
        symbol_ctx = sym.get("summary", "No symbol context available.")
    except Exception:
        symbol_ctx = "Symbol index failed."
        
    model = getattr(settings, "PLANNER_MODEL", "qwen3:4b")
    
    prompt = f"""You are a Senior Application Security Engineer.
You have been given a raw JSON report of potential vulnerabilities generated by static analysis tools (Bandit & Semgrep).

--- RAW FINDINGS ---
{json.dumps(raw_findings, indent=2)}

--- PROJECT CONTEXT (SYMBOL INDEX) ---
{symbol_ctx}

Your task:
1. Review each raw finding.
2. Cross-reference it with the Project Context if applicable.
3. Filter out obvious false positives.
4. For the valid findings, write a clear, plain-English explanation of WHY it is a vulnerability and HOW to fix it.
5. Prioritize them by severity (critical, high, medium).

Return a STRICT JSON object in this exact format (NO MARKDOWN WRAPPERS):
{{
  "summary": "1-2 sentence overall risk assessment",
  "vulnerabilities": [
    {{
      "severity": "critical|high|medium",
      "file": "path/to/file.py",
      "line_number": 42,
      "issue_type": "Brief issue name (e.g., SQL Injection)",
      "explanation": "Clear explanation of the flaw and the fix"
    }}
  ]
}}
"""
    
    logger.info("Triaging findings with LLM...")
    try:
        res = await model_manager.generate_completion(
            prompt=prompt,
            model=model,
            temperature=0.1,
            max_tokens=2000,
            system_prompt="You are a strict JSON data generator. Output ONLY valid JSON.",
            expect_json=True
        )
        
        # Clean markdown wrappers if any
        res_str = res.strip()
        import re
        match = re.search(r'\{.*\}', res_str, re.DOTALL)
        if match:
            res_str = match.group(0)
            
        return json.loads(res_str)
    except Exception as e:
        logger.error(f"LLM Triage failed: {e}")
        # Fallback to raw translation
        return {
            "summary": "LLM Triage failed. Returning raw findings.",
            "vulnerabilities": [
                {
                    "severity": r.get("issue_severity", "low").lower(),
                    "file": r.get("filename", "unknown"),
                    "line_number": r.get("line_number", 0),
                    "issue_type": r.get("test_name", "Unknown"),
                    "explanation": r.get("issue_text", "No details")
                }
                for r in raw_findings
            ]
        }

async def start_hybrid_scan(session_id: str, project_name: str, target_url: str = None, db_url: str = None):
    """Background task to run the hybrid scan."""
    try:
        project_root = os.path.join(settings.WORKSPACE_ROOT, "projects", project_name)
        if not os.path.isdir(project_root):
            # Fallback for flat workspaces
            project_root = settings.WORKSPACE_ROOT
            
        _SCANNER_SESSIONS[session_id] = {
            "status": "running",
            "progress": "Running deterministic SAST scanners (Bandit + Semgrep)...",
            "report": None
        }
        
        # 1. Deterministic Scans Concurrently (Zero-LLM)
        from app.performance_scanner import run_performance_scan
        from app.qa_scanner import _run_existing_tests
        from app.e2e_scanner import _run_e2e_tests
        from app.hardware_context import hardware_context
        
        hardware_profile = hardware_context.get_profile()
        max_concurrency = hardware_profile.get("max_concurrent_scans", 1)
        
        # We use a semaphore to respect the hardware concurrency limit
        sem = asyncio.Semaphore(max_concurrency)
        
        async def _run_with_sem(coro):
            async with sem:
                return await coro
                
        results = await asyncio.gather(
            _run_with_sem(_run_bandit_scan(project_root)),
            _run_with_sem(_run_semgrep_scan(project_root)),
            _run_with_sem(run_performance_scan(project_root, target_url, db_url)),
            _run_with_sem(_run_existing_tests(project_root)),
            _run_with_sem(_run_e2e_tests(target_url))
        )
        
        # Aggregate all raw findings
        raw_findings = results[0] + results[1] + results[2] + results[3] + results[4]
        
        _SCANNER_SESSIONS[session_id]["progress"] = f"AI Triaging {len(raw_findings)} potential vulnerabilities..."
        
        # 2. AI Triage
        final_report = await _triage_with_llm(raw_findings, project_root)
        
        _SCANNER_SESSIONS[session_id] = {
            "status": "completed",
            "progress": "Scan complete.",
            "report": final_report
        }
        logger.info(f"Hybrid scan completed for {session_id}")
        
    except Exception as e:
        logger.error(f"Hybrid scan failed for {session_id}: {e}")
        _SCANNER_SESSIONS[session_id] = {
            "status": "failed",
            "progress": f"Error: {str(e)}",
            "report": None
        }
