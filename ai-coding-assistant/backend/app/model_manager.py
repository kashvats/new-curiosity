import logging
import json
from typing import Optional, Dict, Any, List
import httpx
from app.config import settings

import asyncio

logger = logging.getLogger(__name__)

# Lazy semaphore — created on first use inside the running event loop.
# Semaphore(1) = one Ollama inference at a time. Safe to raise to 2-3 on strong hardware.
_ollama_semaphore: Optional[asyncio.Semaphore] = None

def _get_semaphore() -> asyncio.Semaphore:
    global _ollama_semaphore
    if _ollama_semaphore is None:
        _ollama_semaphore = asyncio.Semaphore(1)
    return _ollama_semaphore


class ModelManager:
    """Manage LLM API calls."""
    
    def __init__(self):
        self.openai_api_key = settings.OPENAI_API_KEY
        self.anthropic_api_key = settings.ANTHROPIC_API_KEY
        # Persistent HTTP clients — one connection pool reused across all calls
        self._ollama_client = httpx.AsyncClient(timeout=600.0)
        self._openai_client = httpx.AsyncClient(timeout=600.0)
        self._anthropic_client = httpx.AsyncClient(timeout=600.0)
    
    async def aclose(self):
        """Gracefully close all persistent HTTP clients."""
        await self._ollama_client.aclose()
        await self._openai_client.aclose()
        await self._anthropic_client.aclose()
    
    async def generate_completion(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = None,
        max_tokens: int = None,
        system_prompt: Optional[str] = None,
        expect_json: bool = False
    ) -> str:
        """Generate completion using configured LLM."""
        if model is None:
            model = settings.DEFAULT_MODEL
        if temperature is None:
            temperature = settings.DEFAULT_TEMPERATURE
        if max_tokens is None:
            max_tokens = settings.DEFAULT_MAX_TOKENS
        
        if "gpt" in model.lower():
            return await self._call_openai(prompt, model, temperature, max_tokens, system_prompt, expect_json)
        elif "claude" in model.lower():
            return await self._call_anthropic(prompt, model, temperature, max_tokens, system_prompt, expect_json)
        else:
            return await self._call_ollama(prompt, model, temperature, max_tokens, system_prompt, expect_json)
            
    def _trigger_background_pull(self, model: str):
        """Trigger a model pull in the background so future requests succeed."""
        ollama_url = getattr(settings, "OLLAMA_BASE_URL", getattr(settings, "ollama_base_url", "http://host.docker.internal:11434"))
        url = f"{ollama_url.rstrip('/')}/api/pull"
        
        async def pull_task():
            try:
                logger.info(f"Starting background pull for missing model: '{model}'")
                async with httpx.AsyncClient(timeout=3600.0) as client:
                    await client.post(url, json={"model": model})
                logger.info(f"Background pull of '{model}' complete.")
            except Exception as e:
                logger.warning(f"Background pull of '{model}' failed: {e}")
                
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(pull_task())
        except RuntimeError:
            pass
    
    async def _call_openai(
        self,
        prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
        system_prompt: Optional[str],
        expect_json: bool = False
    ) -> str:
        """Call OpenAI API."""
        if not self.openai_api_key:
            raise ValueError("OpenAI API key not configured")
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        response = await self._openai_client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.openai_api_key}"},
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
    
    async def _call_anthropic(
        self,
        prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
        system_prompt: Optional[str],
        expect_json: bool = False
    ) -> str:
        """Call Anthropic API."""
        if not self.anthropic_api_key:
            raise ValueError("Anthropic API key not configured")
        
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        if system_prompt:
            payload["system"] = system_prompt

        response = await self._anthropic_client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.anthropic_api_key,
                "anthropic-version": "2023-06-01"
            },
            json=payload
        )
        response.raise_for_status()
        data = response.json()
        return data["content"][0]["text"]
            
    async def _call_ollama(
        self,
        prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
        system_prompt: Optional[str],
        expect_json: bool = False,
        _is_fallback: bool = False
    ) -> str:
        """Call local Ollama instance."""
        ollama_url = getattr(settings, "OLLAMA_BASE_URL", getattr(settings, "ollama_base_url", "http://host.docker.internal:11434"))
        url = f"{ollama_url.rstrip('/')}/api/generate"
        
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"
            
        payload = {
            "model": model,
            "prompt": full_prompt,
            "stream": False,
            "keep_alive": -1,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens
            }
        }
        
        if expect_json:
            payload["format"] = "json"
        
        async with _get_semaphore():
            try:
                response = await self._ollama_client.post(url, json=payload)
                response.raise_for_status()
                return response.json().get("response", "")
            except httpx.TimeoutException:
                raise Exception("LLM generation timed out (exceeded 10 minutes). The codebase might be too large, or the local model is still processing. Please try again.")
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404 and not _is_fallback:
                    fallback = getattr(settings, "PLANNER_MODEL", settings.DEFAULT_MODEL)
                    logger.warning(f"Model '{model}' not found in Ollama. Triggering background pull and falling back to '{fallback}'.")
                    self._trigger_background_pull(model)
                    return await self._call_ollama(prompt, fallback, temperature, max_tokens, system_prompt, expect_json, _is_fallback=True)
                raise Exception(f"LLM API Error: {e.response.text}")
            except Exception as e:
                raise Exception(f"Failed to connect to local LLM: {repr(e)}")
            
    async def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        temperature: float = None,
        max_tokens: int = None
    ) -> Dict[str, Any]:
        """Chat completion that supports tool calling."""
        if model is None:
            model = settings.DEFAULT_MODEL
        if temperature is None:
            temperature = settings.DEFAULT_TEMPERATURE
            
        # Currently defaults to Ollama's /api/chat. 
        # Add OpenAI/Anthropic branches here if needed later.
        return await self._chat_ollama_with_tools(messages, tools, model, temperature)

    async def _chat_ollama_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        model: str,
        temperature: float,
        _is_fallback: bool = False
    ) -> Dict[str, Any]:
        """Call Ollama /api/chat endpoint with tools."""
        ollama_url = getattr(settings, "OLLAMA_BASE_URL", getattr(settings, "ollama_base_url", "http://host.docker.internal:11434"))
        url = f"{ollama_url.rstrip('/')}/api/chat"
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": -1,
            "options": {
                "temperature": temperature
            }
        }
        
        if tools:
            payload["tools"] = tools
            
        async with _get_semaphore():
            try:
                response = await self._ollama_client.post(url, json=payload)
                response.raise_for_status()
                return response.json().get("message", {})
            except httpx.TimeoutException:
                raise Exception("LLM chat timed out. Please try again.")
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404 and not _is_fallback:
                    fallback = getattr(settings, "PLANNER_MODEL", settings.DEFAULT_MODEL)
                    logger.warning(f"Model '{model}' not found in Ollama. Triggering background pull and falling back to '{fallback}'.")
                    self._trigger_background_pull(model)
                    return await self._chat_ollama_with_tools(messages, tools, fallback, temperature, _is_fallback=True)
                raise Exception(f"LLM Chat API Error: {e.response.text}")
            except Exception as e:
                raise Exception(f"Failed to connect to local LLM chat endpoint: {repr(e)}")
            
    async def generate_completion_stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None
    ):
        """Generate streaming completion based on provider."""
        model = model or settings.DEFAULT_MODEL
        temperature = temperature if temperature is not None else settings.DEFAULT_TEMPERATURE
        max_tokens = max_tokens or settings.DEFAULT_MAX_TOKENS
        
        if "gpt" in model.lower() or "claude" in model.lower():
            # For simplicity, fallback to non-stream if not Ollama, or yield the whole response
            # In a real scenario, we'd implement OpenAI/Anthropic streaming here
            resp = await self.generate_completion(prompt, model, temperature, max_tokens, system_prompt)
            yield resp
        else:
            async for chunk in self._call_ollama_stream(prompt, model, temperature, max_tokens, system_prompt):
                yield chunk

    async def _call_ollama_stream(
        self,
        prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
        system_prompt: Optional[str],
        _is_fallback: bool = False
    ):
        ollama_url = getattr(settings, "OLLAMA_BASE_URL", "http://host.docker.internal:11434")
        url = f"{ollama_url.rstrip('/')}/api/generate"
        
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"
            
        payload = {
            "model": model,
            "prompt": full_prompt,
            "stream": True,
            "keep_alive": -1,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens
            }
        }
        
        # Streaming acquires the semaphore for the entire stream to protect the GPU
        async with _get_semaphore():
            try:
                async with self._ollama_client.stream("POST", url, json=payload) as response:
                    if response.status_code == 404 and not _is_fallback:
                        fallback = getattr(settings, "PLANNER_MODEL", settings.DEFAULT_MODEL)
                        logger.warning(f"Model '{model}' not found in Ollama. Triggering background pull and falling back to '{fallback}'.")
                        self._trigger_background_pull(model)
                        async for chunk in self._call_ollama_stream(prompt, fallback, temperature, max_tokens, system_prompt, _is_fallback=True):
                            yield chunk
                        return
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line:
                            try:
                                data = json.loads(line)
                                if "response" in data:
                                    yield data["response"]
                            except json.JSONDecodeError:
                                pass
            except httpx.HTTPStatusError as e:
                raise Exception(f"LLM Stream API Error: {e.response.text}")


# Global instance
model_manager = ModelManager()

def get_effective_model(role: str) -> str:
    """Helper to return the default model for a given role."""
    return settings.DEFAULT_MODEL
