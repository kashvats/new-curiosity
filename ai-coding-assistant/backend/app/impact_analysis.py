"""
Phase 52: Impact Analysis Engine
"""
import logging
import os
from typing import Dict, Any

from app.embeddings import get_embedding
from app.qdrant_store import search_vectors
from app.model_manager import model_manager
from app.config import settings

logger = logging.getLogger(__name__)


async def analyze_impact(target_file: str, proposed_change: str) -> Dict[str, Any]:
    """
    Predicts the impact of a code change by finding dependent files in the Codebase Index
    and asking the LLM to analyze the blast radius.
    """
    logger.info(f"Running impact analysis for {target_file}...")
    
    basename = os.path.basename(target_file)
    
    # 1. Search the codebase for references to this file (simulated dependency graph)
    try:
        query_vector = get_embedding(basename)
        code_collection = getattr(settings, "QDRANT_CODE_COLLECTION", "codebase")
        
        # We don't use strict filters here to cast a wide net across the codebase
        results = search_vectors(
            query_vector=query_vector,
            limit=5,
            score_threshold=0.5,
            collection_name=code_collection
        )
        
        context_chunks = []
        for r in results:
            path = r.get("metadata", {}).get("file_path", "Unknown")
            if path != target_file: # Don't include the file itself, we want dependents
                text = r.get("metadata", {}).get("content", "")
                context_chunks.append(f"--- FILE: {path} ---\n{text}\n")
                
        dependent_context = "\n".join(context_chunks)
        if not dependent_context:
            dependent_context = "No direct cross-file dependencies found in the semantic index."
            
    except Exception as e:
        logger.warning(f"Semantic search failed during impact analysis: {e}")
        dependent_context = f"Could not fetch dependents: {e}"

    # 2. Build the LLM prompt
    prompt = f"""You are an expert QA Engineer and Systems Analyst.
A developer is planning to modify a file in the project.
Your task is to analyze the "blast radius" of this change and predict what else might break.

TARGET FILE: {target_file}

PROPOSED CHANGE:
{proposed_change}

POSSIBLE DEPENDENT FILES (From Semantic Search):
{dependent_context}

Analyze the impact and output a Markdown report. Include:
1. High-Level Risk Assessment (Low/Medium/High).
2. Which specific files or modules are most likely to break if this change is made.
3. What the developer must test before committing this change.
4. Any API contracts or database schemas that might be violated.

Return ONLY clean Markdown formatting. Do not use strict JSON.
"""

    try:
        model = getattr(settings, "PLANNER_MODEL", "qwen3:4b")
        response = await model_manager.generate_completion(
            prompt=prompt,
            model=model,
            temperature=0.1,
            max_tokens=4000,
            system_prompt="You are a strict code quality analyst."
        )
        
        logger.info("Successfully generated impact analysis.")
        return {
            "status": "ok",
            "model_used": model,
            "impact_report_md": response.strip()
        }
        
    except Exception as e:
        logger.error(f"Failed to generate impact analysis: {e}")
        return {"status": "error", "message": str(e)}
