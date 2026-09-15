"""
Phase 58: Autonomous Project Auditor
"""
import asyncio
import logging
import uuid
import json
import os
import hashlib
import re
from datetime import datetime, timezone
from typing import Dict, Any

from app.database import get_db
from app.architecture import generate_architecture_map
from app.model_manager import model_manager
from app.config import settings

logger = logging.getLogger(__name__)

async def run_project_audit(project_path: str, project_name: str) -> Dict[str, Any]:
    """
    Runs the Map-Reduce Project Auditor workflow:
    1. Grabs the architecture map (Phase 51)
    2. Runs 3 parallel expert LLM audits (Security, Architecture, Best Practices)
    3. Reduces the JSON findings into a single Master Audit Report
    4. Saves the report to SQLite.
    """
    logger.info("Starting Map-Reduce Autonomous Project Audit...")
    
    # 1. Gather Architecture Map
    arch_res = await generate_architecture_map(project_path)
    arch_map = arch_res.get("architecture_map_md", "Could not generate architecture map.")
    
    # Audit Result Cache: if arch map hasn't changed since last audit, return cached report instantly
    arch_hash = hashlib.sha256(arch_map.encode("utf-8")).hexdigest()
    try:
        with get_db() as conn:
            cached_audit = conn.execute(
                """SELECT id, overall_status, summary_json, findings_json, fix_queue_json, created_at
                   FROM project_audit_reports
                   WHERE scope = ? AND arch_hash = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (project_name, arch_hash)
            ).fetchone()
            if cached_audit:
                logger.info(f"Audit Cache HIT for '{project_name}'. Returning cached report.")
                row = dict(cached_audit)
                return {
                    "status": "ok",
                    "cached": True,
                    "report_id": row["id"],
                    "overall_status": row["overall_status"],
                    "summary": json.loads(row["summary_json"]),
                    "findings": json.loads(row["findings_json"]),
                    "fix_queue": json.loads(row["fix_queue_json"]),
                }
    except Exception as e:
        logger.warning(f"Audit cache check failed, proceeding with full audit: {e}")
    
    # 2. Gather Error Logs
    error_logs = "No recent system errors found."
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='error_memory'")
            if cursor.fetchone():
                cursor.execute(
                    "SELECT created_at, command, error_output, successful_fix FROM error_memory WHERE project_path = ? ORDER BY created_at DESC LIMIT 10",
                    (project_path,)
                )
                errors = [dict(row) for row in cursor.fetchall()]
                if errors:
                    error_logs = json.dumps(errors, indent=2)
                    if len(error_logs) > 2500:
                        error_logs = error_logs[:2500] + "\n...[TRUNCATED]"
    except Exception as e:
        logger.warning(f"Failed to fetch error memory for audit: {e}")

    # 3. Map Phase: Define 3 expert prompts
    model = getattr(settings, "PLANNER_MODEL", "qwen3:4b")
    fast_model = getattr(settings, "FAST_MODEL", "qwen2.5:0.5b")

    # Parse project manifest (zero-LLM, deterministic)
    manifest_context = ""
    try:
        from app.workspace_tools import parse_project_manifest
        profile = parse_project_manifest(project_path)
        services_txt = "\n".join(
            f"  - {s['name']}: {s['language']}/{s['framework']} port={s['port']} install='{s['install_cmd']}'"
            for s in profile.get("services", [])
        )
        manifest_context = f"""PROJECT MANIFEST (factual, no guessing):
- Language: {profile['language']} | Framework: {profile['framework']}
- Test runner: {profile['test_runner']}
- Services: {len(profile['services'])} detected\n{services_txt}
- has_docker={profile['has_docker']} has_cicd={profile['has_cicd']} has_tests={profile['has_tests']} has_readme={profile['has_readme']} has_env_example={profile['has_env_example']}
"""
        logger.info(f"Manifest parsed: {profile['language']}/{profile['framework']}, {len(profile['services'])} services")
    except Exception as e:
        logger.warning(f"Manifest parse failed (non-critical): {e}")
        manifest_context = "Manifest: could not be parsed."

    # Compress the arch map into a short bullet-list to save tokens across all 3 expert prompts
    try:
        compress_prompt = f"""Summarize this project architecture in 10 concise bullet points.
Focus on: tech stack, key components, data flow, and entry points.
Be extremely brief. No fluff.

Architecture:
{arch_map}
"""
        compressed_context = await model_manager.generate_completion(
            prompt=compress_prompt,
            model=fast_model,
            temperature=0.1,
            max_tokens=400,
            system_prompt="You are a technical writer. Output only bullet points."
        )
        logger.info("Audit context compressed successfully.")
    except Exception as e:
        logger.warning(f"Context compression failed, using full arch map: {e}")
        compressed_context = arch_map
    
    def generate_expert_prompt(instructions: str, category: str) -> str:
        return f"""You are an Expert Auditor for a software project.
--- ARCHITECTURE SUMMARY ---
{compressed_context}
--- PROJECT MANIFEST (USE THIS FOR FACTUAL CHECKS) ---
{manifest_context}
--- RECENT ERRORS ---
{error_logs}

{instructions}

Return a STRICT JSON object in this exact format (NO MARKDOWN WRAPPERS):
{{
  "overall_status": "good" | "warning" | "critical",
  "summary": "1 sentence summary",
  "findings": [
    {{
      "severity": "high" | "medium" | "low",
      "category": "{category}",
      "problem": "Specific problem",
      "recommended_action": "Specific fix"
    }}
  ],
  "fix_queue": [
    {{
      "priority": 1,
      "task": "Highly detailed fix task",
      "likely_files": ["path/to/file.py"]
    }}
  ]
}}
"""

    prompts = [
        generate_expert_prompt(
            "Focus ONLY on architectural flaws, monolithic designs, missing dependency injection, or structure issues.",
            "architecture"
        ),
        generate_expert_prompt(
            "Focus ONLY on security vulnerabilities, exposed secrets, and unhandled errors (bugs).",
            "security"
        ),
        generate_expert_prompt(
            """Check ONLY for missing DevOps and quality files. For each item below, determine if it is present based on the architecture summary. If it is MISSING, add a fix_queue entry with the exact expected file path in likely_files. Do NOT flag these as generic issues.
- Dockerfile or docker-compose.yml (containerization)
- .github/workflows/*.yml OR .gitlab-ci.yml OR Jenkinsfile (CI/CD pipeline)
- A tests/ or test/ directory containing test files (unit/integration tests)
- README.md (project documentation)
- .env.example (environment variable template)
Only flag items that are genuinely absent. Do not invent problems.""",
            "best_practices"
        )
    ]

    async def fetch_expert_audit(prompt_text):
        try:
            res = await model_manager.generate_completion(
                prompt=prompt_text,
                model=model,
                temperature=0.1,
                max_tokens=2000,
                system_prompt="You are a strict JSON data generator. Output ONLY valid JSON.",
                expect_json=True
            )
            
            # Robust JSON extraction
            res_str = res.strip()
            match = re.search(r'\{.*\}', res_str, re.DOTALL)
            if match:
                res_str = match.group(0)
            return json.loads(res_str)
        except Exception as e:
            logger.warning(f"Expert LLM failed: {e}")
            return {"overall_status": "warning", "summary": f"Failed expert scan: {e}", "findings": [], "fix_queue": []}

    # Execute Map Phase — the _ollama_lock Semaphore handles GPU queuing safely
    results = list(await asyncio.gather(*[fetch_expert_audit(p) for p in prompts]))
    
    # 4. Reduce Phase: Aggregate findings
    logger.info("Map phase complete. Synthesizing Master Audit Report...")
    reduce_prompt = f"""You are a Lead Software Auditor. You have just received 3 sub-audit reports from your expert team regarding the architecture, security, and best practices of a project.

Here are the raw JSON reports from your experts:
{json.dumps(results, indent=2)}

Your task is to synthesize these into a single, cohesive Master Audit Report.
- Write a professional, deduplicated Executive Summary.
- Deduplicate any overlapping findings or fix_queue tasks.
- Return the final Master Report using the EXACT SAME strict JSON format as the expert reports.

Return ONLY a strict JSON object (NO MARKDOWN WRAPPERS).
"""
    try:
        master_res = await model_manager.generate_completion(
            prompt=reduce_prompt,
            model=model,
            temperature=0.2,
            max_tokens=4000,
            system_prompt="You are a strict JSON data generator. Output ONLY valid JSON.",
            expect_json=True
        )
        
        res_str = master_res.strip()
        match = re.search(r'\{.*\}', res_str, re.DOTALL)
        if match:
            res_str = match.group(0)
            
        audit_data = json.loads(res_str)
        
        # Ensure fix_queue is sorted by priority
        if "fix_queue" in audit_data and isinstance(audit_data["fix_queue"], list):
            audit_data["fix_queue"] = sorted(audit_data["fix_queue"], key=lambda x: x.get("priority", 99))
            
    except Exception as e:
        logger.error(f"Failed to synthesize master audit report: {e}")
        # Fallback to naive concatenation if the heavy model fails the reduce step
        master_findings = []
        master_queue = []
        summaries = []
        highest_status = "good"
        status_weights = {"critical": 3, "warning": 2, "good": 1}
        for res in results:
            master_findings.extend(res.get("findings", []))
            master_queue.extend(res.get("fix_queue", []))
            summaries.append(res.get("summary", ""))
            status = res.get("overall_status", "good").lower()
            if status_weights.get(status, 1) > status_weights.get(highest_status, 1):
                highest_status = status
        audit_data = {
            "overall_status": highest_status,
            "summary": " ".join([s for s in summaries if s]),
            "findings": master_findings,
            "fix_queue": sorted(master_queue, key=lambda x: x.get("priority", 99))
        }
        
    report_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    
    # 4. Generate Markdown Report
    md_content = f"# AI Project Audit Report: {project_name}\n"
    md_content += f"**Date:** {created_at}\n\n"
    md_content += f"## Health Status: `{audit_data.get('overall_status', 'UNKNOWN').upper()}`\n\n"
    md_content += f"### Executive Summary\n{audit_data.get('summary', 'No summary provided.')}\n\n"
    
    md_content += "### Key Findings & Vulnerabilities\n"
    findings = audit_data.get("findings", [])
    if findings:
        for f in findings:
            md_content += f"- **[{f.get('severity', 'LOW').upper()}] {f.get('category', 'General')}**: {f.get('problem', 'Issue')}\n"
            md_content += f"  - *Recommendation:* {f.get('recommended_action', 'N/A')}\n"
    else:
        md_content += "*No critical findings detected.*\n"
        
    md_content += "\n### Recommended Action Queue\n"
    fix_queue = audit_data.get("fix_queue", [])
    if fix_queue:
        for q in fix_queue:
            md_content += f"- **[Priority {q.get('priority', 'N/A')}]**: {q.get('task', 'Task')}\n"
            md_content += f"  - *Likely Files:* `{', '.join(q.get('likely_files', []))}`\n"
    else:
        md_content += "*No actions queued.*\n"
        
    # 5. Save to File System
    report_file_path = os.path.join(project_path, "AUDIT_REPORT.md")
    try:
        with open(report_file_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        logger.info(f"Audit report saved natively to {report_file_path}")
    except Exception as file_err:
        logger.error(f"Failed to write markdown report to {report_file_path}: {file_err}")

    # 6. Save to Database for Frontend Dashboard History
    with get_db() as conn:
        conn.execute(
            """INSERT INTO project_audit_reports 
               (id, scope, overall_status, summary_json, findings_json, recommendations_json, fix_queue_json, arch_hash, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report_id,
                project_name,
                audit_data.get("overall_status", "unknown"),
                json.dumps(audit_data.get("summary", "")),
                json.dumps(audit_data.get("findings", [])),
                "[]",
                json.dumps(audit_data.get("fix_queue", [])),
                arch_hash,
                datetime.now(timezone.utc).isoformat()
            )
        )
        conn.commit()

    return {
        "status": "ok",
        "report_id": report_id,
        "report_path": report_file_path,
        "overall_status": audit_data.get("overall_status"),
        "summary": audit_data.get("summary"),
        "findings": audit_data.get("findings", []),
        "fix_queue": audit_data.get("fix_queue", [])
    }
