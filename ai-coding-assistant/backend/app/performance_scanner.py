import os
import json
import uuid
import asyncio
import subprocess
import logging
from typing import Dict, Any, List

from app.hardware_context import hardware_context

logger = logging.getLogger(__name__)

# Basic Semgrep rules to detect N+1 Queries and O(N^2) complexity
PERFORMANCE_RULES_YAML = """
rules:
  - id: n-plus-one-query-python
    languages: [python]
    message: "Potential N+1 Query detected. Database query executed inside a loop."
    severity: WARNING
    patterns:
      - pattern-either:
          - pattern: |
              for ... in ...:
                  ...
                  $SESSION.query(...)
          - pattern: |
              for ... in ...:
                  ...
                  $SESSION.execute(...)
  - id: nested-loops-js
    languages: [javascript, typescript]
    message: "O(N^2) Complexity: Nested loops detected. Consider using a Set or Map."
    severity: WARNING
    patterns:
      - pattern: |
          for (...) {
            ...
            for (...) {
              ...
            }
          }
  - id: nested-loops-python
    languages: [python]
    message: "O(N^2) Complexity: Nested loops detected. Consider using a dictionary or set for lookups."
    severity: WARNING
    patterns:
      - pattern: |
          for $X in $Y:
              ...
              for $A in $B:
                  ...
"""

async def _run_dynamic_load_test(target_url: str, profile: Dict) -> Dict:
    import httpx
    import time
    
    if not profile.get("enable_load_testing"):
        return {"issue_type": "Load Test Skipped", "explanation": "Skipped due to low system memory."}
        
    logger.info(f"Starting Load Test against {target_url} with max RPS: {profile['load_test_max_rps']}")
    
    concurrency = min(50, profile['load_test_max_rps'])
    
    async def fetch(client):
        try:
            start = time.time()
            res = await client.get(target_url, timeout=3.0)
            return time.time() - start, res.status_code
        except Exception:
            return -1, 500

    async with httpx.AsyncClient() as client:
        tasks = [fetch(client) for _ in range(concurrency)]
        results = await asyncio.gather(*tasks)
        
    valid_times = [r[0] for r in results if r[0] > 0]
    if not valid_times:
        return {"severity": "critical", "issue_type": "Load Test Failed", "explanation": f"All requests to {target_url} failed."}
        
    avg_latency = sum(valid_times) / len(valid_times)
    return {
        "severity": "info" if avg_latency < 0.5 else "warning",
        "issue_type": "Dynamic Load Test Results",
        "explanation": f"Load test on {target_url} completed. Avg latency: {avg_latency*1000:.2f}ms across {len(valid_times)} concurrent requests."
    }

async def _run_db_profiling(db_url: str) -> List[Dict]:
    import psycopg
    logger.info("Starting Database Profiling via psycopg")
    findings = []
    
    try:
        async with await psycopg.AsyncConnection.connect(db_url) as conn:
            async with conn.cursor() as cur:
                # Query for missing indexes: tables with lots of sequential scans
                query = """
                SELECT relname, seq_scan, idx_scan 
                FROM pg_stat_user_tables 
                WHERE seq_scan > 100 AND (idx_scan IS NULL OR seq_scan > idx_scan * 2);
                """
                await cur.execute(query)
                rows = await cur.fetchall()
                
                for row in rows:
                    relname, seq, idx = row
                    findings.append({
                        "severity": "high",
                        "issue_type": "Missing Database Index",
                        "explanation": f"Table '{relname}' has {seq} sequential scans but only {idx or 0} index scans. Add an index to prevent O(N) lookup degradation."
                    })
    except Exception as e:
        logger.error(f"DB Profiling failed: {e}")
        findings.append({
            "severity": "warning",
            "issue_type": "DB Connection Error",
            "explanation": f"Failed to connect to database for profiling: {str(e)}"
        })
        
    return findings

async def run_performance_scan(project_path: str, target_url: str = None, db_url: str = None) -> List[Dict]:
    """Runs a hardware-aware performance scan on the project."""
    profile = hardware_context.get_profile()
    
    logger.info(f"Running Performance Scan on {project_path} (Profile: {profile['tier']})")
    
    parsed_findings = []
    
    # 1. Static Big-O & Query Analysis via Semgrep
    rules_path = f"/tmp/perf_rules_{uuid.uuid4().hex}.yaml"
    
    try:
        with open(rules_path, "w") as f:
            f.write(PERFORMANCE_RULES_YAML)
            
        abs_project_path = os.path.abspath(project_path)
        
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{abs_project_path}:/src",
            "-v", f"{os.path.abspath(rules_path)}:/rules.yaml",
            "returntocorp/semgrep", "semgrep", "--config", "/rules.yaml", "/src", "--json", "--quiet"
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
        except asyncio.TimeoutError:
            logger.error("Performance Semgrep scan timed out after 300s. Killing process.")
            process.kill()
            await process.wait()
            stdout, stderr = b"", b""
        
        if process.returncode == 0 and stdout:
            try:
                output = json.loads(stdout.decode())
                for r in output.get("results", []):
                    parsed_findings.append({
                        "severity": "warning",
                        "file": r.get("path", ""),
                        "line_number": r.get("start", {}).get("line", 0),
                        "issue_type": r.get("check_id", "performance_issue"),
                        "explanation": r.get("extra", {}).get("message", "")
                    })
            except json.JSONDecodeError:
                pass
                
    finally:
        if os.path.exists(rules_path):
            os.remove(rules_path)
            
    # 2. Dynamic Load Testing
    if target_url:
        load_result = await _run_dynamic_load_test(target_url, profile)
        load_result["file"] = "N/A"
        load_result["line_number"] = 0
        parsed_findings.append(load_result)
        
    # 3. Dynamic Database Profiling
    if db_url:
        db_results = await _run_db_profiling(db_url)
        for dr in db_results:
            dr["file"] = "Database Schema"
            dr["line_number"] = 0
            parsed_findings.append(dr)
            
    return parsed_findings
