import logging
import httpx
from typing import Dict, Any, List
from app.config import settings
from app.model_manager import model_manager

logger = logging.getLogger(__name__)

def sanitize_query(query: str) -> str:
    """Sanitize the search query according to Phase 12 rules."""
    query = query.strip()
    if not query:
        raise ValueError("Search query cannot be empty.")
    if len(query) > 500:
        raise ValueError("Search query exceeds 500 characters.")
    return query

def is_safe_url(url: str) -> bool:
    """Block local or dangerous URLs."""
    lower_url = url.lower()
    if lower_url.startswith("file://") or lower_url.startswith("javascript:"):
        return False
    return True

def normalize_search_results(raw_results: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Convert SearXNG results into the standard normalized format."""
    normalized = []
    for r in raw_results:
        url = r.get("url", "")
        if not is_safe_url(url):
            continue
            
        normalized.append({
            "title": r.get("title", "No Title"),
            "url": url,
            "snippet": r.get("content", ""),
            "source": r.get("engine", "unknown")
        })
    return normalized

async def search_searxng(query: str, max_results: int = 8) -> List[Dict[str, str]]:
    """Execute search against the configured SearXNG instance."""
    url = f"{settings.SEARXNG_BASE_URL.rstrip('/')}/search"
    params = {
        "q": query,
        "format": "json",
        "language": "en",
        "safesearch": 1
    }
    
    try:
        async with httpx.AsyncClient(timeout=settings.WEB_SEARCH_TIMEOUT_SECONDS) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            raw_results = data.get("results", [])
            
            # Limit results
            raw_results = raw_results[:max_results]
            return normalize_search_results(raw_results)
    except Exception as e:
        logger.error(f"SearXNG search failed: {e}")
        # Phase 12 requirement: return empty/handled gracefully without crashing backend
        return []

async def summarize_search_results(query: str, results: List[Dict[str, str]]) -> str:
    """Use the local LLM to summarize snippets."""
    if not results:
        return "No results found to summarize."
        
    context = ""
    for idx, r in enumerate(results, 1):
        context += f"Result {idx}:\nTitle: {r['title']}\nURL: {r['url']}\nSnippet: {r['snippet']}\n\n"
        
    prompt = f"""You are a helpful assistant. The user searched for: '{query}'.
Here are the snippets returned from a web search.
IMPORTANT: You only have these snippets, you have NOT read the full web pages. Make sure to explicitly mention this limitation if it is relevant.
Please provide a concise summary of the information found in these snippets. Include the URLs as useful references.

Snippets:
{context}
"""
    
    try:
        # We use CODER_MODEL for everything since the internal architecture was unified
        summary = await model_manager.generate_completion(
            prompt=prompt,
            model=settings.CODER_MODEL,
            temperature=0.3,
            max_tokens=2000
        )
        return summary
    except Exception as e:
        logger.error(f"Failed to summarize search results: {e}")
        return "Failed to generate summary due to LLM error."

async def search_web(query: str, max_results: int = 8, summarize: bool = False) -> Dict[str, Any]:
    """
    Main hook for Web Search. 
    Retrieves results, optionally summarizes them, and formats the memory candidate.
    """
    if settings.WEB_SEARCH_PROVIDER != "searxng":
        return {
            "status": "error",
            "provider": settings.WEB_SEARCH_PROVIDER,
            "message": f"Unsupported provider: {settings.WEB_SEARCH_PROVIDER}"
        }
        
    try:
        safe_query = sanitize_query(query)
        safe_max = min(max_results, settings.WEB_SEARCH_MAX_RESULTS)
        
        results = await search_searxng(safe_query, safe_max)
        
        if not results:
             return {
                "status": "error",
                "provider": "searxng",
                "message": "SearXNG is not reachable or returned no results."
            }
            
        response = {
            "status": "ok",
            "provider": "searxng",
            "query": safe_query,
            "results": results
        }
        
        if summarize:
            summary = await summarize_search_results(safe_query, results)
            response["summary"] = summary
            response["can_save_to_memory"] = True
            response["memory_candidate"] = {
                "title": f"Web Search: {safe_query}",
                "content": summary,
                "source_type": "web_search_summary",
                "query": safe_query,
                "urls": [r["url"] for r in results]
            }
            
        return response
        
    except ValueError as e:
        return {
            "status": "error",
            "provider": settings.WEB_SEARCH_PROVIDER,
            "message": str(e)
        }
    except Exception as e:
        logger.error(f"Web search hook failed: {e}")
        return {
            "status": "error",
            "provider": settings.WEB_SEARCH_PROVIDER,
            "message": f"Internal error during search: {str(e)}"
        }
