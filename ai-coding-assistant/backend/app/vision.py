import json
import logging
import httpx
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)

async def describe_image(base64_image: str) -> Optional[str]:
    """
    Passes a base64 encoded image to a local Vision model (e.g. llava) via Ollama
    to generate a highly detailed textual description of diagrams and flowcharts.
    Crucially, sets keep_alive to 0 to instantly unload the model and protect VRAM.
    """
    
    # We allow the user to configure the vision model, default to llava
    vision_model = getattr(settings, "VISION_MODEL", "llava:7b")
    
    prompt = (
        "You are an expert system architect and data analyst. "
        "Look at this diagram or flowchart and describe it in EXTREME detail. "
        "Extract every word of text, every box, and explain exactly how the arrows connect the boxes. "
        "If it is a UI mockup, describe the layout. "
        "Your output must be structured Markdown. Do NOT skip any details, as your text will completely replace this image in a database."
    )
    
    payload = {
        "model": vision_model,
        "prompt": prompt,
        "images": [base64_image],
        "stream": False,
        "keep_alive": 0  # CRITICAL: Unload immediately after generation to save VRAM
    }
    
    ollama_url = getattr(settings, "OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    
    try:
        logger.info(f"Triggering VLM {vision_model} to describe extracted image...")
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{ollama_url}/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()
            description = data.get("response", "").strip()
            
            if description:
                logger.info(f"VLM successfully generated a {len(description)}-character description.")
                return f"\n\n[DIAGRAM/IMAGE DESCRIPTION START]\n{description}\n[DIAGRAM/IMAGE DESCRIPTION END]\n\n"
            else:
                logger.warning("VLM returned an empty description.")
                return None
                
    except Exception as e:
        logger.error(f"Failed to extract image description via VLM: {e}")
        return None
