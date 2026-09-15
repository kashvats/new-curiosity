import logging
from urllib.parse import urlparse
from typing import Dict, Any, Optional
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright

from app.config import settings

logger = logging.getLogger(__name__)

def validate_url(url: str, interactive: bool = False) -> str:
    """
    Validate URLs against strict safety rules.
    - Block file://, javascript:, data:, chrome:, about:
    - Block local filesystem paths
    - Block empty URLs
    - If interactive (click/type), strict host whitelist applies.
    """
    if not url or not url.strip():
        raise ValueError("URL cannot be empty.")
        
    parsed = urlparse(url)
    
    # Block dangerous protocols
    if parsed.scheme.lower() in ["file", "javascript", "data", "chrome", "about"]:
        raise ValueError(f"Dangerous or restricted protocol blocked: {parsed.scheme}")
        
    # Ensure it's http/https
    if parsed.scheme.lower() not in ["http", "https"]:
        raise ValueError(f"Only http/https protocols are allowed. Blocked: {parsed.scheme}")
        
    # For state-modifying interactive actions, limit to safe hosts
    if interactive:
        allowed_hosts = [h.strip().lower() for h in settings.BROWSER_ALLOWED_HOSTS.split(",")]
        if parsed.hostname and parsed.hostname.lower() not in allowed_hosts:
            raise ValueError(f"Interactive actions (click/type) are blocked on external host: {parsed.hostname}")
            
    return url

async def get_browser_context():
    """Context manager wrapper for playwright would be ideal, but for hooks we init locally."""
    pass # Will be handled inside functions to ensure cleanup

async def open_page(url: str) -> Dict[str, Any]:
    safe_url = validate_url(url)
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=settings.BROWSER_HEADLESS)
            page = await browser.new_page()
            
            # 30 second default timeout
            await page.goto(safe_url, timeout=settings.BROWSER_TIMEOUT_SECONDS * 1000)
            
            title = await page.title()
            final_url = page.url
            
            await browser.close()
            
            return {
                "status": "ok",
                "url": safe_url,
                "title": title,
                "final_url": final_url
            }
    except Exception as e:
        logger.error(f"Failed to open page {safe_url}: {e}")
        return {"status": "error", "message": str(e)}

async def get_page_text(url: str, max_chars: int = 5000) -> Dict[str, Any]:
    safe_url = validate_url(url)
    max_chars = min(max_chars, 20000) # Hard limit from spec
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=settings.BROWSER_HEADLESS)
            page = await browser.new_page()
            
            await page.goto(safe_url, timeout=settings.BROWSER_TIMEOUT_SECONDS * 1000)
            
            title = await page.title()
            # Extract visible text using innerText of body
            body_element = await page.query_selector("body")
            text = ""
            if body_element:
                text = await body_element.inner_text()
                
            text = text[:max_chars]
            
            await browser.close()
            
            return {
                "status": "ok",
                "url": safe_url,
                "title": title,
                "text": text
            }
    except Exception as e:
        logger.error(f"Failed to get page text for {safe_url}: {e}")
        return {"status": "error", "message": str(e)}

async def take_screenshot(url: str, full_page: bool = True) -> Dict[str, Any]:
    safe_url = validate_url(url)
    
    try:
        screenshot_dir = Path(settings.BROWSER_SCREENSHOT_DIR)
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"screenshot_{timestamp}.png"
        filepath = screenshot_dir / filename
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=settings.BROWSER_HEADLESS)
            page = await browser.new_page()
            
            await page.goto(safe_url, timeout=settings.BROWSER_TIMEOUT_SECONDS * 1000)
            title = await page.title()
            
            await page.screenshot(path=str(filepath), full_page=full_page)
            
            await browser.close()
            
            return {
                "status": "ok",
                "url": safe_url,
                "title": title,
                "screenshot_path": str(filepath)
            }
    except Exception as e:
        logger.error(f"Failed to take screenshot of {safe_url}: {e}")
        return {"status": "error", "message": str(e)}

async def click_element(url: str, selector: str, confirm: bool) -> Dict[str, Any]:
    if not confirm:
        return {"status": "error", "message": "Click action rejected: explicit confirmation required."}
    if not selector:
        return {"status": "error", "message": "Selector cannot be empty."}
        
    safe_url = validate_url(url, interactive=True)
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=settings.BROWSER_HEADLESS)
            page = await browser.new_page()
            
            await page.goto(safe_url, timeout=settings.BROWSER_TIMEOUT_SECONDS * 1000)
            await page.click(selector, timeout=5000)
            
            # Wait for any navigation or state updates
            await page.wait_for_load_state("networkidle", timeout=5000)
            
            title = await page.title()
            final_url = page.url
            
            await browser.close()
            
            return {
                "status": "ok",
                "url": safe_url,
                "title": title,
                "final_url": final_url,
                "clicked_selector": selector
            }
    except Exception as e:
        logger.error(f"Failed to click element on {safe_url}: {e}")
        return {"status": "error", "message": str(e)}

async def type_text(url: str, selector: str, text: str, confirm: bool) -> Dict[str, Any]:
    if not confirm:
        return {"status": "error", "message": "Type action rejected: explicit confirmation required."}
    if not selector:
        return {"status": "error", "message": "Selector cannot be empty."}
        
    safe_url = validate_url(url, interactive=True)
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=settings.BROWSER_HEADLESS)
            page = await browser.new_page()
            
            await page.goto(safe_url, timeout=settings.BROWSER_TIMEOUT_SECONDS * 1000)
            await page.fill(selector, text, timeout=5000)
            
            title = await page.title()
            final_url = page.url
            
            await browser.close()
            
            return {
                "status": "ok",
                "url": safe_url,
                "title": title,
                "final_url": final_url,
                "typed_selector": selector
            }
    except Exception as e:
        logger.error(f"Failed to type text on {safe_url}: {e}")
        return {"status": "error", "message": str(e)}
