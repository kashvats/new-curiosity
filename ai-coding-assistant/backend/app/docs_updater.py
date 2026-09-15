import os
import hashlib
import json
import httpx
from datetime import datetime, timezone
from bs4 import BeautifulSoup
import logging
from app.qdrant_store import upsert_chunk_vector, search_vectors
from app.embeddings import get_embedding
from app.model_manager import model_manager, get_effective_model

logger = logging.getLogger(__name__)

async def identify_docs_source(technology: str) -> dict:
    """Identify official documentation source, stable version, etc., using the LLM."""
    prompt = f"""
    Identify the official documentation source for the technology: '{technology}'.
    Do not use beta, canary, nightly, experimental, preview, alpha, or release-candidate docs.
    Only return official documentation website or GitHub repository.
    Return the response as JSON exactly matching this format:
    {{
        "technology": "{technology}",
        "official_url": "URL to the stable documentation",
        "stable_version": "e.g., 18.2.0 or 3.0",
        "github_repo": "e.g., facebook/react (if applicable)",
        "release_channel": "stable",
        "is_official": true
    }}
    """
    try:
        model = get_effective_model("planner")
        response_text = await model_manager.generate_completion(
            prompt=prompt,
            model=model
        )
        return json.loads(response_text)
    except Exception as e:
        logger.error(f"Failed to identify docs source: {e}")
        # Fallback for common frameworks if LLM fails
        return {
            "technology": technology,
            "official_url": f"https://{technology.lower()}.org/docs",
            "stable_version": "latest-stable",
            "github_repo": "",
            "release_channel": "stable",
            "is_official": True
        }

from urllib.parse import urljoin, urlparse

async def crawl_site(start_url: str, max_pages: int = 50) -> list:
    """Crawl a website starting at start_url, returning a list of tuples (url, html)."""
    visited = set()
    queue = [start_url]
    html_pages = []
    
    base_parsed = urlparse(start_url)
    # Strip any trailing slashes from path to match cleanly
    base_path = base_parsed.path.rstrip('/')
    base_prefix = f"{base_parsed.scheme}://{base_parsed.netloc}{base_path}"
    
    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
        while queue and len(visited) < max_pages:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            
            try:
                response = await client.get(url)
                response.raise_for_status()
                html = response.text
                
                soup = BeautifulSoup(html, "html.parser")
                
                # Find links
                for a in soup.find_all("a", href=True):
                    next_url = urljoin(url, a["href"])
                    next_url = next_url.split('#')[0] # Remove fragment
                    # Only queue links that start with the same base path
                    if next_url not in visited and next_url.startswith(base_prefix):
                        queue.append(next_url)
                        
                # Remove junk tags
                for tag in soup(["nav", "aside", "footer", "script", "style", "iframe", "header", "button"]):
                    tag.decompose()
                    
                # Remove elements by common junk classes
                junk_classes = ["sidebar", "menu", "ads", "advertisement", "cookie-banner", "toc"]
                for class_name in junk_classes:
                    for el in soup.find_all(class_=lambda c: c and class_name in c.lower()):
                        el.decompose()
                        
                html_pages.append((url, str(soup)))
            except Exception as e:
                logger.error(f"Error fetching {url}: {e}")
                
    return html_pages

def chunk_semantically(html: str, metadata_template: dict) -> list:
    """Chunk the cleaned HTML semantically by headers."""
    soup = BeautifulSoup(html, "html.parser")
    chunks = []
    
    current_topic = metadata_template.get("technology", "General")
    current_section = "Overview"
    current_content = []
    
    # Simple semantic chunking: split by h1, h2, h3
    for element in soup.body.descendants if soup.body else soup.descendants:
        if element.name in ["h1", "h2", "h3"]:
            # Save previous chunk
            text = " ".join(current_content).strip()
            if text and len(text) > 50:
                chunk_meta = metadata_template.copy()
                chunk_meta["topic"] = current_topic
                chunk_meta["section_title"] = current_section
                chunks.append({"text": f"{current_section}\n{text}", "metadata": chunk_meta})
                
            current_section = element.get_text(strip=True)
            if element.name == "h1":
                current_topic = current_section
            current_content = []
            
        elif element.name in ["p", "pre", "code", "li"]:
            text = element.get_text(separator=' ', strip=True)
            if text:
                # Basic deduplication of consecutive identical text
                if not current_content or current_content[-1] != text:
                    current_content.append(text)
                    
    # Save last chunk
    text = " ".join(current_content).strip()
    if text and len(text) > 50:
        chunk_meta = metadata_template.copy()
        chunk_meta["topic"] = current_topic
        chunk_meta["section_title"] = current_section
        chunks.append({"text": f"{current_section}\n{text}", "metadata": chunk_meta})
        
    return chunks

async def process_technology_docs(technology: str, custom_url: str = None) -> dict:
    """Main pipeline to fetch, chunk, and ingest official docs."""
    result = {
        "technology": technology,
        "stable_version": "custom" if custom_url else "",
        "source_used": custom_url or "",
        "chunks_added": 0,
        "chunks_updated": 0,
        "chunks_skipped": 0,
        "warnings": [],
        "next_recommended_update": ""
    }
    
    if custom_url:
        url = custom_url
        info = {"stable_version": "custom", "release_channel": "custom"}
    else:
        info = await identify_docs_source(technology)
        if not info.get("is_official"):
            result["warnings"].append("Could not verify an official stable source.")
            return result
            
        result["stable_version"] = info.get("stable_version", "unknown")
        url = info.get("official_url", "")
        result["source_used"] = url
        
        if not url:
            result["warnings"].append("No valid URL found.")
            return result
            
    # Crawl the documentation recursively
    pages = await crawl_site(url, max_pages=50)
    if not pages:
        result["warnings"].append(f"Failed to fetch {url}")
        return result
        
    now = datetime.now(timezone.utc).isoformat()
    
    metadata_template = {
        "technology": technology,
        "doc_version": info.get("stable_version", "custom"),
        "release_channel": info.get("release_channel", "stable"),
        "source_url": url,
        "source_type": "official_docs",
        "trust_level": "high",
        "allowed_in_ide": True,
        "chat_type": "ide",
        "retrieved_at": now,
        "last_checked_at": now,
        "superseded": False,
        "filename": f"{technology}_docs_{info.get('stable_version', 'custom')}.md"
    }
    
    for page_url, html in pages:
        # Update the source_url for this specific chunk
        page_meta_template = metadata_template.copy()
        page_meta_template["source_url"] = page_url
        
        chunks = chunk_semantically(html, page_meta_template)
        
        for chunk in chunks:
            text = chunk["text"]
            meta = chunk["metadata"]
            
            content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            meta["content_hash"] = content_hash
            
            meta["text"] = text
            vector = get_embedding(text)
            
            try:
                from qdrant_client.http.models import Filter, FieldCondition, MatchValue
                from app.qdrant_store import get_client
                from app.config import settings
                client = get_client()
                
                # Check identical chunk
                match = client.scroll(
                    collection_name=settings.QDRANT_COLLECTION,
                    scroll_filter=Filter(
                        must=[FieldCondition(key="content_hash", match=MatchValue(value=content_hash))]
                    ),
                    limit=1
                )[0]
                
                if match:
                    result["chunks_skipped"] += 1
                    continue
                    
                # Check for superseded chunks
                old_versions = client.scroll(
                    collection_name=settings.QDRANT_COLLECTION,
                    scroll_filter=Filter(
                        must=[
                            FieldCondition(key="technology", match=MatchValue(value=technology)),
                            FieldCondition(key="section_title", match=MatchValue(value=meta["section_title"]))
                        ]
                    ),
                    limit=10
                )[0]
                
                for old in old_versions:
                    if old.payload.get("content_hash") != content_hash:
                        old.payload["superseded"] = True
                        client.set_payload(
                            collection_name=settings.QDRANT_COLLECTION,
                            payload=old.payload,
                            points=[old.id]
                        )
                
                import uuid
                point_id = str(uuid.uuid4())
                upsert_chunk_vector(point_id, vector, meta)
                
                if old_versions:
                    result["chunks_updated"] += 1
                else:
                    result["chunks_added"] += 1
                    
            except Exception as e:
                logger.error(f"Error checking Qdrant for hash: {e}")
                import uuid
                upsert_chunk_vector(str(uuid.uuid4()), vector, meta)
                result["chunks_added"] += 1
                
    result["next_recommended_update"] = "30 days"
    
    # Update SQLite database
    total_chunks = result["chunks_added"] + result["chunks_updated"] + result["chunks_skipped"]
    try:
        from app.database import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO official_docs 
            (technology, source_url, version, chunk_count, last_updated)
            VALUES (?, ?, ?, ?, ?)
        """, (
            technology,
            result["source_used"],
            result["stable_version"],
            total_chunks,
            now
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to update official_docs table: {e}")
        
    return result
