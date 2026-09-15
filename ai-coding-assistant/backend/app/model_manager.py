import logging
import json
import time
from typing import Optional, Dict, Any, List
import httpx
from app.config import settings
from app.model_usage import record_model_usage

import asyncio

logger = logging.getLogger(__name__)

# Lazy semaphore — one per running event loop.  Reusing an asyncio.Semaphore
# across separate loops (common in tests/reloads) can bind waiters to a closed loop.
# Semaphore(1) = one Ollama inference at a time. Safe to raise to 2-3 on strong hardware.
_ollama_semaphore: Optional[asyncio.Semaphore] = None
_ollama_semaphore_loop: Optional[asyncio.AbstractEventLoop] = None

def _get_semaphore() -> asyncio.Semaphore:
    global _ollama_semaphore, _ollama_semaphore_loop
    loop = asyncio.get_running_loop()
    if _ollama_semaphore is None or _ollama_semaphore_loop is not loop:
        _ollama_semaphore = asyncio.Semaphore(1)
        _ollama_semaphore_loop = loop
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
        
        provider = "openai" if "gpt" in model.lower() else ("anthropic" if "claude" in model.lower() else "ollama")
        started = time.perf_counter()
        prompt_chars = len(prompt or "") + len(system_prompt or "")
        try:
            if provider == "openai":
                result = await self._call_openai(prompt, model, temperature, max_tokens, system_prompt, expect_json)
            elif provider == "anthropic":
                result = await self._call_anthropic(prompt, model, temperature, max_tokens, system_prompt, expect_json)
            else:
                result = await self._call_ollama(prompt, model, temperature, max_tokens, system_prompt, expect_json)
            record_model_usage(
                provider=provider, model=model, operation="completion", prompt_chars=prompt_chars,
                output_chars=len(result or ""), duration_ms=int((time.perf_counter() - started) * 1000), success=True,
            )
            return result
        except Exception as exc:
            record_model_usage(
                provider=provider, model=model, operation="completion", prompt_chars=prompt_chars,
                output_chars=0, duration_ms=int((time.perf_counter() - started) * 1000), success=False,
                error_type=type(exc).__name__,
            )
            raise
            
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
        """Call local Ollama instance without holding the GPU semaphore across fallback.

        A 404 fallback used to recurse while the one-slot semaphore was still held,
        deadlocking forever. Each HTTP attempt now releases the semaphore before a
        fallback model is tried.
        """
        ollama_url = getattr(settings, "OLLAMA_BASE_URL", getattr(settings, "ollama_base_url", "http://host.docker.internal:11434"))
        url = f"{ollama_url.rstrip('/')}/api/generate"

        current_model = model
        fallback_attempt = _is_fallback
        while True:
            full_prompt = prompt if not system_prompt else f"{system_prompt}\n\n{prompt}"
            payload = {
                "model": current_model,
                "prompt": full_prompt,
                "stream": False,
                "keep_alive": -1,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            }
            if expect_json:
                payload["format"] = "json"

            try:
                async with _get_semaphore():
                    response = await self._ollama_client.post(url, json=payload)
                response.raise_for_status()
                return response.json().get("response", "")
            except httpx.TimeoutException:
                raise Exception("LLM generation timed out (exceeded 10 minutes). The codebase might be too large, or the local model is still processing. Please try again.")
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404 and not fallback_attempt:
                    fallback = getattr(settings, "PLANNER_MODEL", settings.DEFAULT_MODEL)
                    if not fallback or fallback == current_model:
                        raise Exception(f"LLM API Error: model '{current_model}' was not found and no distinct fallback is configured")
                    logger.warning(f"Model '{current_model}' not found in Ollama. Triggering background pull and falling back to '{fallback}'.")
                    self._trigger_background_pull(current_model)
                    current_model = fallback
                    fallback_attempt = True
                    continue
                raise Exception(f"LLM API Error: {e.response.text}")
            except Exception as e:
                if isinstance(e, Exception) and str(e).startswith("LLM API Error:"):
                    raise
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
        started = time.perf_counter()
        prompt_chars = len(json.dumps(messages, ensure_ascii=False, default=str))
        try:
            result = await self._chat_ollama_with_tools(messages, tools, model, temperature)
            record_model_usage(
                provider="ollama", model=model, operation="chat_with_tools", prompt_chars=prompt_chars,
                output_chars=len(json.dumps(result, ensure_ascii=False, default=str)),
                duration_ms=int((time.perf_counter() - started) * 1000), success=True,
            )
            return result
        except Exception as exc:
            record_model_usage(
                provider="ollama", model=model, operation="chat_with_tools", prompt_chars=prompt_chars,
                output_chars=0, duration_ms=int((time.perf_counter() - started) * 1000), success=False,
                error_type=type(exc).__name__,
            )
            raise

    async def _chat_ollama_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        model: str,
        temperature: float,
        _is_fallback: bool = False
    ) -> Dict[str, Any]:
        """Call Ollama /api/chat without recursive semaphore deadlock on fallback."""
        ollama_url = getattr(settings, "OLLAMA_BASE_URL", getattr(settings, "ollama_base_url", "http://host.docker.internal:11434"))
        url = f"{ollama_url.rstrip('/')}/api/chat"
        current_model = model
        fallback_attempt = _is_fallback

        while True:
            payload = {
                "model": current_model,
                "messages": messages,
                "stream": False,
                "keep_alive": -1,
                "options": {"temperature": temperature},
            }
            if tools:
                payload["tools"] = tools
            try:
                async with _get_semaphore():
                    response = await self._ollama_client.post(url, json=payload)
                response.raise_for_status()
                return response.json().get("message", {})
            except httpx.TimeoutException:
                raise Exception("LLM chat timed out. Please try again.")
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404 and not fallback_attempt:
                    fallback = getattr(settings, "PLANNER_MODEL", settings.DEFAULT_MODEL)
                    if not fallback or fallback == current_model:
                        raise Exception(f"LLM Chat API Error: model '{current_model}' was not found and no distinct fallback is configured")
                    logger.warning(f"Model '{current_model}' not found in Ollama. Triggering background pull and falling back to '{fallback}'.")
                    self._trigger_background_pull(current_model)
                    current_model = fallback
                    fallback_attempt = True
                    continue
                raise Exception(f"LLM Chat API Error: {e.response.text}")
            except Exception as e:
                if isinstance(e, Exception) and str(e).startswith("LLM Chat API Error:"):
                    raise
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
        """Stream Ollama output and release the semaphore before fallback retry."""
        ollama_url = getattr(settings, "OLLAMA_BASE_URL", "http://host.docker.internal:11434")
        url = f"{ollama_url.rstrip('/')}/api/generate"
        full_prompt = prompt if not system_prompt else f"{system_prompt}\n\n{prompt}"
        current_model = model
        fallback_attempt = _is_fallback

        while True:
            payload = {
                "model": current_model,
                "prompt": full_prompt,
                "stream": True,
                "keep_alive": -1,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            }
            should_fallback = False
            fallback_model = None
            try:
                # Hold the GPU semaphore for one stream only.  If this attempt is a
                # 404, exit the context first, then loop with the fallback model.
                async with _get_semaphore():
                    async with self._ollama_client.stream("POST", url, json=payload) as response:
                        if response.status_code == 404 and not fallback_attempt:
                            fallback_model = getattr(settings, "PLANNER_MODEL", settings.DEFAULT_MODEL)
                            should_fallback = True
                        else:
                            response.raise_for_status()
                            async for line in response.aiter_lines():
                                if not line:
                                    continue
                                try:
                                    data = json.loads(line)
                                except json.JSONDecodeError:
                                    continue
                                if "response" in data:
                                    yield data["response"]
                if should_fallback:
                    if not fallback_model or fallback_model == current_model:
                        raise Exception(f"LLM Stream API Error: model '{current_model}' was not found and no distinct fallback is configured")
                    logger.warning(f"Model '{current_model}' not found in Ollama. Triggering background pull and falling back to '{fallback_model}'.")
                    self._trigger_background_pull(current_model)
                    current_model = fallback_model
                    fallback_attempt = True
                    continue
                return
            except httpx.HTTPStatusError as e:
                raise Exception(f"LLM Stream API Error: {e.response.text}")



# Global instance
model_manager = ModelManager()

def get_effective_model(role: str) -> str:
    """Return the configured model for an agent role.

    This keeps role selection centralized so future hardware-aware routing can replace
    the policy without rewriting every agent.
    """
    role = (role or "").lower().strip()
    mapping = {
        "planner": settings.PLANNER_MODEL,
        "coder": settings.CODER_MODEL,
        "debugger": settings.DEBUGGER_MODEL,
        "reviewer": settings.REVIEWER_MODEL,
        "tester": settings.FAST_MODEL,
        "context": settings.FAST_MODEL,
        "triage": settings.FAST_MODEL,
    }
    return mapping.get(role, settings.DEFAULT_MODEL)
