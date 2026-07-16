"""
Model Router — the single gateway for all LLM requests in ALOY.

Every subsystem (conversation, learning, agent, reasoning, knowledge) must
call ModelRouter instead of touching OllamaClient directly.
"""

import logging
import time
from typing import AsyncGenerator, Dict, Any, List, Optional

from .ollama_client import OllamaClient
from .coordinator import ModelCoordinator, Priority
from .tracker import ModelTracker

logger = logging.getLogger(__name__)


from .config import MODELS_CONFIG

# ======================================================================
# Routing table  (from Architecture Review V2, §14)
# ======================================================================
ROUTING_TABLE: Dict[str, Dict[str, Any]] = {
    "classification": {
        "primary": MODELS_CONFIG["vision"]["name"],
        "fallback": MODELS_CONFIG["chat"]["name"],
        "priority": Priority.CONVERSATION,
    },
    "simple_chat": {
        "primary": MODELS_CONFIG["vision"]["name"],
        "fallback": MODELS_CONFIG["chat"]["name"],
        "priority": Priority.CONVERSATION,
    },
    "complex_chat": {
        "primary": MODELS_CONFIG["coding"]["name"],
        "fallback": MODELS_CONFIG["chat"]["name"],
        "priority": Priority.CONVERSATION,
    },
    "coding_request": {
        "primary": MODELS_CONFIG["coding"]["name"],
        "fallback": MODELS_CONFIG["chat"]["name"],
        "priority": Priority.CONVERSATION,
    },
    "coding_fast": {
        "primary": MODELS_CONFIG["coding"]["name"],
        "fallback": MODELS_CONFIG["chat"]["name"],
        "priority": Priority.CONVERSATION,
    },
    "reasoning_request": {
        "primary": MODELS_CONFIG["reasoning"]["name"],
        "fallback": MODELS_CONFIG["chat"]["name"],
        "priority": Priority.CONVERSATION,
    },
    "agent_planning": {
        "primary": MODELS_CONFIG["vision"]["name"],
        "fallback": MODELS_CONFIG["coding"]["name"],
        "priority": Priority.AGENT,
    },
    "agent_coding": {
        "primary": MODELS_CONFIG["coding"]["name"],
        "fallback": MODELS_CONFIG["chat"]["name"],
        "priority": Priority.AGENT,
    },
    "memory_generation": {
        "primary": MODELS_CONFIG["vision"]["name"],
        "fallback": MODELS_CONFIG["chat"]["name"],
        "priority": Priority.BACKGROUND,
    },
    "summarization": {
        "primary": MODELS_CONFIG["vision"]["name"],
        "fallback": MODELS_CONFIG["chat"]["name"],
        "priority": Priority.BACKGROUND,
    },
    "embedding": {
        "primary": MODELS_CONFIG["embedding"]["name"],
        "fallback": None,
        "priority": Priority.BACKGROUND,
    },
    "reflection": {
        "primary": MODELS_CONFIG["coding"]["name"],
        "fallback": MODELS_CONFIG["chat"]["name"],
        "priority": Priority.BACKGROUND,
    },
    # Catch-all defaults
    "memory_query": {
        "primary": MODELS_CONFIG["vision"]["name"],
        "fallback": MODELS_CONFIG["chat"]["name"],
        "priority": Priority.CONVERSATION,
    },
    "tool_request": {
        "primary": MODELS_CONFIG["vision"]["name"],
        "fallback": MODELS_CONFIG["chat"]["name"],
        "priority": Priority.CONVERSATION,
    },
    "planning_request": {
        "primary": MODELS_CONFIG["vision"]["name"],
        "fallback": MODELS_CONFIG["chat"]["name"],
        "priority": Priority.CONVERSATION,
    },
    "meta_request": {
        "primary": MODELS_CONFIG["vision"]["name"],
        "fallback": MODELS_CONFIG["chat"]["name"],
        "priority": Priority.CONVERSATION,
    },
}


class ModelRouter:
    """Centralized model routing with fallback, tracking, and coordination."""

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        max_concurrent: int = 1,
        telemetry=None,
    ):
        self.client = OllamaClient(base_url=ollama_url)
        self.coordinator = ModelCoordinator(max_concurrent=max_concurrent)
        self.tracker = ModelTracker()
        self.telemetry = telemetry
        from conversation.token_manager import TokenBudgetManager
        self.token_manager = TokenBudgetManager()

        # conversation_id → model name (conversation continuity)
        self._conversation_models: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public: is_busy  (used by Learning Engine budget check)
    # ------------------------------------------------------------------
    def is_busy(self) -> bool:
        return self.coordinator.is_busy()

    # ------------------------------------------------------------------
    # Public: resolve model for a task
    # ------------------------------------------------------------------
    def resolve_model(
        self,
        task: str,
        conversation_id: Optional[str] = None,
    ) -> str:
        """Return the model name to use for *task*.

        If *conversation_id* is supplied and a model was already used for
        that conversation, prefer it for continuity.
        """
        if conversation_id and conversation_id in self._conversation_models:
            return self._conversation_models[conversation_id]

        route = ROUTING_TABLE.get(task, ROUTING_TABLE["simple_chat"])
        return route["primary"]

    # ------------------------------------------------------------------
    # Public: non-streaming generation
    # ------------------------------------------------------------------
    async def generate(
        self,
        task: str,
        prompt: str,
        options: Optional[Dict[str, Any]] = None,
        conversation_id: Optional[str] = None,
    ) -> str:
        """Non-streaming LLM generation with fallback and tracking."""
        route = ROUTING_TABLE.get(task, ROUTING_TABLE["simple_chat"])
        primary = route["primary"]
        fallback = route.get("fallback")
        priority = route.get("priority", Priority.CONVERSATION)

        keep_alive = "10s" if priority == Priority.BACKGROUND else "5m"

        model = primary
        selection_reason = f"resolved as primary for task '{task}'"
        if conversation_id and conversation_id in self._conversation_models:
            model = self._conversation_models[conversation_id]
            selection_reason = f"conversation continuity lock for conversation '{conversation_id}'"

        logger.info("ModelRouter.generate: selected model '%s' (reason: %s)", model, selection_reason)

        await self.coordinator.acquire(priority)
        try:
            tokens_in = self.token_manager.count_tokens(prompt)
            start_time = time.perf_counter()
            result = await self._try_generate(model, prompt, options, task, keep_alive)
            duration_ms = (time.perf_counter() - start_time) * 1000
            
            tokens_out = self.token_manager.count_tokens(result)
            if self.telemetry:
                self.telemetry.record_model_call(model, task, tokens_in, tokens_out, duration_ms)

            # Track conversation continuity
            if conversation_id:
                self._conversation_models[conversation_id] = model

            return result

        except Exception as primary_err:
            self.tracker.record_error(model, task)
            logger.warning("Primary model %s failed for %s: %s", model, task, primary_err)

            if fallback and fallback != model:
                try:
                    logger.info("ModelRouter.generate: falling back to model '%s' (reason: primary model failed)", fallback)
                    tokens_in = self.token_manager.count_tokens(prompt)
                    start_time = time.perf_counter()
                    result = await self._try_generate(fallback, prompt, options, task, keep_alive)
                    duration_ms = (time.perf_counter() - start_time) * 1000
                    
                    tokens_out = self.token_manager.count_tokens(result)
                    if self.telemetry:
                        self.telemetry.record_model_call(fallback, task, tokens_in, tokens_out, duration_ms)
                        
                    if conversation_id:
                        self._conversation_models[conversation_id] = fallback
                    return result
                except Exception as fb_err:
                    self.tracker.record_error(fallback, task)
                    logger.error("Fallback model %s also failed: %s", fallback, fb_err)
                    raise fb_err
            raise primary_err
        finally:
            await self.coordinator.release()

    # ------------------------------------------------------------------
    # Public: streaming generation
    # ------------------------------------------------------------------
    async def stream(
        self,
        task: str,
        prompt: str,
        options: Optional[Dict[str, Any]] = None,
        conversation_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Streaming LLM generation with tracking.

        Fallback is NOT supported mid-stream — if the primary model fails
        before the first token we raise immediately so the caller can
        retry with `generate()` or display an error.
        """
        route = ROUTING_TABLE.get(task, ROUTING_TABLE["simple_chat"])
        primary = route["primary"]
        priority = route.get("priority", Priority.CONVERSATION)

        keep_alive = "10s" if priority == Priority.BACKGROUND else "5m"

        model = primary
        selection_reason = f"resolved as primary for task '{task}'"
        if conversation_id and conversation_id in self._conversation_models:
            model = self._conversation_models[conversation_id]
            selection_reason = f"conversation continuity lock for conversation '{conversation_id}'"

        logger.info("ModelRouter.stream: selected model '%s' (reason: %s)", model, selection_reason)

        await self.coordinator.acquire(priority)
        start = time.perf_counter()
        try:
            tokens_in = self.token_manager.count_tokens(prompt)
            full_response: List[str] = []
            async for token in self.client.stream(model, prompt, options, keep_alive=keep_alive):
                full_response.append(token)
                yield token

            elapsed = (time.perf_counter() - start) * 1000
            self.tracker.record_success(model, task, elapsed)
            
            result_str = "".join(full_response)
            tokens_out = self.token_manager.count_tokens(result_str)
            if self.telemetry:
                self.telemetry.record_model_call(model, task, tokens_in, tokens_out, elapsed)

            if conversation_id:
                self._conversation_models[conversation_id] = model

        except Exception as e:
            self.tracker.record_error(model, task)
            logger.error("Streaming failed for %s with %s: %s", task, model, e)
            yield " [Connection Error]"
        finally:
            await self.coordinator.release()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    async def _try_generate(
        self,
        model: str,
        prompt: str,
        options: Optional[Dict[str, Any]],
        task: str,
        keep_alive: str,
    ) -> str:
        start = time.perf_counter()
        result = await self.client.generate(model, prompt, options, keep_alive=keep_alive)
        elapsed = (time.perf_counter() - start) * 1000
        self.tracker.record_success(model, task, elapsed)
        return result

    async def preload_model(self, model_name: str) -> bool:
        """Preload a model into VRAM dynamically."""
        try:
            logger.info("Preloading model %s into VRAM...", model_name)
            await self.client.generate(model_name, "", keep_alive="5m")
            logger.info("Model %s preloaded successfully.", model_name)
            return True
        except Exception as e:
            logger.warning("Failed to preload model %s: %s", model_name, e)
            return False

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------
    def clear_conversation(self, conversation_id: str) -> None:
        """Drop the conversation-continuity binding."""
        self._conversation_models.pop(conversation_id, None)
