import asyncio
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

async def _run_e2e_tests(target_url: str) -> List[Dict]:
    """Runs a basic Playwright UI test against the target_url to capture JS errors."""
    if not target_url:
        return []
        
    logger.info(f"Running E2E UI tests against {target_url}")
    findings = []
    
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright is not installed. Skipping E2E tests.")
        return []

    try:
        async with async_playwright() as p:
            # We use chromium headless for lightweight execution
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            # Listen for console errors
            page.on("pageerror", lambda err: findings.append({
                "filename": "E2E UI Test",
                "line_number": 0,
                "test_name": "JS Console Exception",
                "issue_severity": "HIGH",
                "issue_text": f"Uncaught JavaScript error on page: {err}"
            }))
            
            page.on("console", lambda msg: findings.append({
                "filename": "E2E UI Test",
                "line_number": 0,
                "test_name": "JS Console Error",
                "issue_severity": "MEDIUM",
                "issue_text": f"Console Error: {msg.text}"
            }) if msg.type == "error" else None)
            
            # Navigate to the target url with a 15-second timeout
            try:
                response = await page.goto(target_url, timeout=15000, wait_until="networkidle")
                if response and not response.ok:
                    findings.append({
                        "filename": "E2E UI Test",
                        "line_number": 0,
                        "test_name": "HTTP Error",
                        "issue_severity": "HIGH",
                        "issue_text": f"Page returned HTTP {response.status} ({response.status_text})"
                    })
            except Exception as e:
                findings.append({
                    "filename": "E2E UI Test",
                    "line_number": 0,
                    "test_name": "Navigation Failure",
                    "issue_severity": "HIGH",
                    "issue_text": f"Failed to load {target_url}: {str(e)}"
                })
            
            await browser.close()
            
    except Exception as e:
        logger.error(f"E2E Testing failed: {e}")
        findings.append({
            "filename": "E2E Framework",
            "line_number": 0,
            "test_name": "Playwright Crash",
            "issue_severity": "MEDIUM",
            "issue_text": f"Browser automation failed: {str(e)}"
        })
        
    return findings
