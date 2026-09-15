"""
Search result reranking and knowledge classification.
"""
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def detect_task_mode(query: str) -> str:
    """Classify the user query into IDE mode or Learn mode."""
    query_lower = query.lower()
    ide_keywords = ["code", "debug", "fix", "generate", "test", "deploy", "build", "create", "error", "issue", "crash", "implement", "function", "refactor"]
    learn_keywords = ["explain", "learn", "concept", "tutorial", "what is", "how does", "theory", "guide", "understand", "why"]
    
    ide_score = sum(1 for kw in ide_keywords if kw in query_lower)
    learn_score = sum(1 for kw in learn_keywords if kw in query_lower)
    
    if ide_score >= learn_score and ide_score > 0:
        return "ide"
    elif learn_score > ide_score:
        return "learn"
    else:
        # Default to IDE mode for a coding assistant
        return "ide"

def classify_document(filename: str) -> dict:
    """Classify a document into a knowledge category based on its filename."""
    if not filename:
        return {"mode": "general", "type": "General"}
        
    name_lower = filename.lower()
    
    # Learn Mode Sources
    if any(kw in name_lower for kw in ["book", "encyclopedia"]):
        return {"mode": "learn", "type": "Books"}
    if any(kw in name_lower for kw in ["tutorial", "guide", "learn", "course"]):
        return {"mode": "learn", "type": "Tutorials"}
    if any(kw in name_lower for kw in ["linux", "security", "reference", "manual"]):
        return {"mode": "learn", "type": "Reference Material"}
        
    # IDE Mode Sources
    if any(kw in name_lower for kw in ["memory", "project", "architecture"]):
        return {"mode": "ide", "type": "Project Memory"}
    if any(kw in name_lower for kw in ["doc", "official", "api"]):
        return {"mode": "ide", "type": "Official Docs"}
    if any(kw in name_lower for kw in ["example", "snippet", "pattern"]):
        return {"mode": "ide", "type": "Verified Examples"}
    if any(kw in name_lower for kw in ["error", "fix", "history", "bug"]):
        return {"mode": "ide", "type": "Error/Fix History"}
    if any(kw in name_lower for kw in ["infrastructure", "deploy", "docker", "k8s"]):
        return {"mode": "ide", "type": "Infrastructure"}
    if any(kw in name_lower for kw in ["test", "spec", "mock"]):
        return {"mode": "ide", "type": "Test Patterns"}
        
    # Fallback for generic names
    return {"mode": "general", "type": "General"}

def rerank_results(query: str, results: List[Dict[str, Any]], top_k: int = 10) -> List[Dict[str, Any]]:
    """
    Rerank search results based on query relevance and strict knowledge classification priority rules.
    Does not require re-ingesting vectors, relies purely on payload metadata.
    """
    if not results:
        return []
        
    task_mode = detect_task_mode(query)
    logger.info(f"Reranking {len(results)} results for task mode: {task_mode.upper()}")
    
    for res in results:
        filename = res.get("filename") or res.get("original_filename") or ""
        classification = classify_document(filename)
        res["classification"] = classification
        
        # Base vector score is usually 0.0 - 1.0. We add large bucket scores to guarantee strict priority separation.
        base_score = res.get("score", 0.0)
        bucket_score = 0
        
        # 1. Use explicit trust_level from payload if available (created by Memory Manager)
        explicit_trust = res.get("trust_level")
        if explicit_trust is not None:
            if task_mode == "ide":
                # In IDE mode, strict trust score hierarchy
                bucket_score = explicit_trust * 10
            else:
                # In Learn mode, Learning Resources (60) get boosted, but not above Memory (100)
                if explicit_trust == 60:
                    bucket_score = 900 # Boost books/tutorials in learn mode
                else:
                    bucket_score = explicit_trust * 10
        else:
            # 2. Fallback to filename inference
            doc_type = classification["type"]
            if task_mode == "ide":
                # Priority: Project Memory -> Official Docs -> Verified Examples -> Error/Fix History -> Web Official Docs -> Learn Sources
                if doc_type == "Project Memory": bucket_score = 1000
                elif doc_type == "Official Docs": bucket_score = 950
                elif doc_type == "Verified Examples": bucket_score = 900
                elif doc_type == "Error/Fix History": bucket_score = 950
                elif doc_type in ["Infrastructure", "Test Patterns"]: bucket_score = 850
                elif doc_type == "Books": bucket_score = 0 # STRICT RULE: Books never outrank official documentation
                else: bucket_score = 500
            else:
                # Priority: Books -> Tutorials -> Reference Material -> Official Docs -> Web
                if doc_type == "Books": bucket_score = 1000
                elif doc_type == "Tutorials": bucket_score = 950
                elif doc_type == "Reference Material": bucket_score = 900
                elif doc_type == "Official Docs": bucket_score = 850
                else: bucket_score = 500
                
        # 3. Penalize Deprecated/Beta Content
        status = res.get("status", "stable").lower()
        if status in ["deprecated", "unsupported"]:
            bucket_score -= 500 # Severe penalty
        elif status in ["beta", "alpha", "experimental", "preview"]:
            bucket_score -= 200 # Moderate penalty
            
        # 4. Version Matching Boost
        version = res.get("version", "").lower()
        if version and version in query.lower():
            bucket_score += 50 # Boost if the specific version is mentioned in the query
            
        res["rerank_score"] = bucket_score + base_score
        
    # Sort strictly by our computed priority buckets, using the vector score to break ties within the same bucket
    sorted_results = sorted(results, key=lambda x: x.get("rerank_score", 0), reverse=True)
    return sorted_results[:top_k]

def calculate_text_overlap(query: str, text: str) -> float:
    """Calculate simple word overlap between query and text."""
    query_words = set(query.lower().split())
    text_words = set(text.lower().split())
    
    if not query_words:
        return 0.0
    
    overlap = len(query_words & text_words)
    return overlap / len(query_words)
