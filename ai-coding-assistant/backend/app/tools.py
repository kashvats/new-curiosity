import httpx
from fastapi import APIRouter, HTTPException
from app.config import settings
from app.models import WebSearchRequest, WebSearchResponse, BrowserOpenRequest, BrowserTextRequest, BrowserScreenshotRequest, BrowserClickRequest, BrowserTypeRequest, BrowserResponse
from app.web_search import search_web
from app.browser_control import open_page, get_page_text, take_screenshot, click_element, type_text
from app.run_history import create_run, complete_run, fail_run
from app.prompt_library import render_template

router = APIRouter(prefix="/tools", tags=["tools"])

@router.post("/web-search", response_model=WebSearchResponse)
async def web_search_endpoint(req: WebSearchRequest):
    try:
        template_text = None
        if req.template_id:
            template_text = render_template(req.template_id, req.template_variables or {}, "web_search")
            
        run_id = create_run("web_search", f"Query: {req.query}", settings.web_search_provider)
        result = await search_web(req.query, req.max_results, req.summarize, template_text)
        if result["status"] == "error":
            fail_run(run_id, result["message"])
            return WebSearchResponse(
                status="error",
                provider=settings.web_search_provider,
                message=result["message"]
            )
            
        complete_run(run_id, f"Found {len(result.get('results', []))} results")
        return WebSearchResponse(**result)
    except Exception as e:
        if 'run_id' in locals(): fail_run(run_id, str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/web-search/health")
async def web_search_health_endpoint():
    if settings.web_search_provider.lower() != "searxng":
        return {
            "status": "error",
            "provider": settings.web_search_provider,
            "base_url": settings.searxng_base_url,
            "message": "Unsupported provider"
        }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(settings.searxng_base_url)
            response.raise_for_status()
            return {
                "status": "ok",
                "provider": settings.web_search_provider,
                "base_url": settings.searxng_base_url
            }
    except Exception as e:
        return {
            "status": "error",
            "provider": settings.web_search_provider,
            "base_url": settings.searxng_base_url,
            "message": str(e)
        }

@router.post("/browser/open", response_model=BrowserResponse)
async def browser_open_endpoint(req: BrowserOpenRequest):
    try:
        run_id = create_run("browser_open", f"URL: {req.url}")
        res = await open_page(req.url)
        if res.get("status") == "error": fail_run(run_id, res.get("message"))
        else: complete_run(run_id, f"Title: {res.get('title')}")
        return BrowserResponse(**res)
    except Exception as e:
        if 'run_id' in locals(): fail_run(run_id, str(e))
        return BrowserResponse(status="error", message=str(e))

@router.post("/browser/text", response_model=BrowserResponse)
async def browser_text_endpoint(req: BrowserTextRequest):
    try:
        run_id = create_run("browser_text", f"URL: {req.url}")
        res = await get_page_text(req.url, req.max_chars)
        if res.get("status") == "error": fail_run(run_id, res.get("message"))
        else: complete_run(run_id, "Extracted text")
        return BrowserResponse(**res)
    except Exception as e:
        if 'run_id' in locals(): fail_run(run_id, str(e))
        return BrowserResponse(status="error", message=str(e))

@router.post("/browser/screenshot", response_model=BrowserResponse)
async def browser_screenshot_endpoint(req: BrowserScreenshotRequest):
    try:
        run_id = create_run("browser_screenshot", f"URL: {req.url}")
        res = await take_screenshot(req.url, req.full_page)
        if res.get("status") == "error": fail_run(run_id, res.get("message"))
        else: complete_run(run_id, "Screenshot saved")
        return BrowserResponse(**res)
    except Exception as e:
        if 'run_id' in locals(): fail_run(run_id, str(e))
        return BrowserResponse(status="error", message=str(e))

@router.post("/browser/click", response_model=BrowserResponse)
async def browser_click_endpoint(req: BrowserClickRequest):
    try:
        run_id = create_run("browser_click", f"URL: {req.url}, Selector: {req.selector}")
        res = await click_element(req.url, req.selector, req.confirm)
        if res.get("status") == "error": fail_run(run_id, res.get("message"))
        else: complete_run(run_id, "Clicked element")
        return BrowserResponse(**res)
    except Exception as e:
        if 'run_id' in locals(): fail_run(run_id, str(e))
        return BrowserResponse(status="error", message=str(e))

@router.post("/browser/type", response_model=BrowserResponse)
async def browser_type_endpoint(req: BrowserTypeRequest):
    try:
        run_id = create_run("browser_type", f"URL: {req.url}, Selector: {req.selector}")
        res = await type_text(req.url, req.selector, req.text, req.confirm)
        if res.get("status") == "error": fail_run(run_id, res.get("message"))
        else: complete_run(run_id, "Typed text")
        return BrowserResponse(**res)
    except Exception as e:
        if 'run_id' in locals(): fail_run(run_id, str(e))
        return BrowserResponse(status="error", message=str(e))

@router.get("/browser/health", response_model=BrowserResponse)
async def browser_health_endpoint():
    try:
        import playwright
        return BrowserResponse(
            status="ok",
            browser="chromium",
            headless=settings.browser_headless,
            screenshot_dir=settings.browser_screenshot_dir
        )
    except ImportError:
        return BrowserResponse(status="error", message="Playwright is not installed")
    except Exception as e:
        return BrowserResponse(status="error", message=str(e))
