"""
Low-level Ollama HTTP client.

All LLM communication with Ollama flows through this module. No other module
should import httpx for LLM calls directly.
"""

import logging
import json
import re
from typing import AsyncGenerator, Dict, Any, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Pattern to strip <think>...</think> blocks emitted by reasoning models (qwen3, deepseek-r1)
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=120.0, write=5.0, pool=5.0)


class OllamaClient:
    """Thin async wrapper around the Ollama REST API."""

    def __init__(self, base_url: str = DEFAULT_OLLAMA_URL):
        self.base_url = base_url.rstrip("/")

    # ------------------------------------------------------------------
    # Non-streaming generation
    # ------------------------------------------------------------------
    async def generate(
        self,
        model: str,
        prompt: str,
        options: Optional[Dict[str, Any]] = None,
        keep_alive: Optional[str] = None,
    ) -> str:
        """Generate a complete response (non-streaming)."""
        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
        if options:
            payload["options"] = options
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive

        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.post(
                f"{self.base_url}/api/generate",
                json=payload,
            )
            if resp.status_code != 200:
                body = resp.text
                logger.error("Ollama generate error %s: %s", resp.status_code, body)
                raise RuntimeError(f"Ollama returned {resp.status_code}: {body}")

            data = resp.json()
            return data.get("response", "")

    # ------------------------------------------------------------------
    # Streaming generation
    # ------------------------------------------------------------------
    async def stream(
        self,
        model: str,
        prompt: str,
        options: Optional[Dict[str, Any]] = None,
        keep_alive: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Yield tokens one-by-one from a streaming generation.
        
        Thinking tokens (<think>...</think>) emitted by reasoning models
        (qwen3, deepseek-r1) are buffered and stripped before being yielded
        so the user only sees the actual answer.
        """
        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": True,
        }
        if options:
            payload["options"] = options
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive

        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/generate",
                json=payload,
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    logger.error("Ollama stream error %s: %s", response.status_code, error_text)
                    raise RuntimeError(f"Ollama returned {response.status_code}")

                # Buffer to detect and strip <think>...</think> blocks
                think_buffer = ""
                in_think = False

                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        token = data.get("response", "")
                        if token:
                            if in_think:
                                # Accumulate inside think block
                                think_buffer += token
                                if "</think>" in think_buffer:
                                    # Think block closed — discard it and emit anything after
                                    after = think_buffer.split("</think>", 1)[1]
                                    think_buffer = ""
                                    in_think = False
                                    if after:
                                        yield after
                            else:
                                if "<think>" in token:
                                    # Think block opens within this token
                                    before, rest = token.split("<think>", 1)
                                    if before:
                                        yield before
                                    think_buffer = rest
                                    in_think = True
                                    # Check if block also closes in same token
                                    if "</think>" in think_buffer:
                                        after = think_buffer.split("</think>", 1)[1]
                                        think_buffer = ""
                                        in_think = False
                                        if after:
                                            yield after
                                else:
                                    yield token
                        if data.get("done", False):
                            return
                    except json.JSONDecodeError:
                        pass

    # ------------------------------------------------------------------
    # Model management helpers
    # ------------------------------------------------------------------
    async def list_models(self) -> List[Dict[str, Any]]:
        """Return the list of locally available models."""
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.get(f"{self.base_url}/api/tags")
            if resp.status_code != 200:
                logger.error("Ollama list_models error %s", resp.status_code)
                return []
            data = resp.json()
            return data.get("models", [])

    async def check_model(self, model: str) -> bool:
        """Return True if *model* is pulled locally."""
        models = await self.list_models()
        return any(m.get("name", "").startswith(model) for m in models)

    async def ping(self) -> bool:
        """Return True if Ollama is reachable."""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(2.0)) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False
