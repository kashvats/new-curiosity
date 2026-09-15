import os
import json
import asyncio
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

async def _run_existing_tests(project_path: str) -> List[Dict]:
    """Detects and runs existing test suites in the project."""
    logger.info(f"Running automated test suites in {project_path}")
    
    findings = []
    
    # 1. Detect Python Pytest
    has_pytest = os.path.exists(os.path.join(project_path, "pytest.ini")) or os.path.isdir(os.path.join(project_path, "tests"))
    if has_pytest:
        logger.info("Detected Python test suite. Running pytest...")
        try:
            # 2-minute timeout per test suite — long enough for most projects,
            # short enough to prevent infinite hangs from broken test configs.
            process = await asyncio.create_subprocess_exec(
                "pytest",
                cwd=project_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
            except asyncio.TimeoutError:
                logger.error("pytest timed out after 120s. Killing process.")
                process.kill()
                await process.wait()
                findings.append({
                    "filename": "Test Suite (Python)",
                    "line_number": 0,
                    "test_name": "Test Suite Timeout",
                    "issue_severity": "MEDIUM",
                    "issue_text": "pytest timed out after 120s. Test suite may be hanging or infinitely looping."
                })
                stdout, stderr = b"", b""
            
            if process.returncode and process.returncode != 0:
                findings.append({
                    "filename": "Test Suite (Python)",
                    "line_number": 0,
                    "test_name": "Test Suite Failure",
                    "issue_severity": "HIGH",
                    "issue_text": f"Pytest failed with exit code {process.returncode}. Check test logs."
                })
        except Exception as e:
            logger.error(f"Failed to run pytest: {e}")
            findings.append({
                "filename": "Test Environment",
                "line_number": 0,
                "test_name": "Test Execution Error",
                "issue_severity": "MEDIUM",
                "issue_text": f"Pytest execution failed: {str(e)}"
            })

    # 2. Detect Node NPM Tests
    package_json_path = os.path.join(project_path, "package.json")
    if os.path.exists(package_json_path):
        try:
            with open(package_json_path, 'r', encoding='utf-8') as f:
                pkg = json.load(f)
                if "scripts" in pkg and "test" in pkg["scripts"]:
                    logger.info("Detected Node test suite. Running npm test...")
                    
                    # Ensure npm is safe to run
                    npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
                    
                    process = await asyncio.create_subprocess_exec(
                        npm_cmd, "test",
                        cwd=project_path,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    try:
                        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
                    except asyncio.TimeoutError:
                        logger.error("npm test timed out after 120s. Killing process.")
                        process.kill()
                        await process.wait()
                        findings.append({
                            "filename": "Test Suite (Node)",
                            "line_number": 0,
                            "test_name": "Test Suite Timeout",
                            "issue_severity": "MEDIUM",
                            "issue_text": "npm test timed out after 120s."
                        })
                        stdout, stderr = b"", b""
                    
                    if process.returncode and process.returncode != 0:
                        findings.append({
                            "filename": "Test Suite (Node)",
                            "line_number": 0,
                            "test_name": "Test Suite Failure",
                            "issue_severity": "HIGH",
                            "issue_text": f"npm test failed with exit code {process.returncode}."
                        })
        except Exception as e:
            logger.error(f"Failed to run npm test: {e}")
            
    if not findings and not has_pytest and not os.path.exists(package_json_path):
         logger.info("No test suites detected.")
         
    return findings
