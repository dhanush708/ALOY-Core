import logging
import re
from typing import Optional

from .pipeline import PipelineStage, ConversationContext

logger = logging.getLogger(__name__)


class IntentDetectionStage(PipelineStage):
    """Classifies user intent — heuristic-first, LLM-fallback via Model Router."""

    INTENTS = [
        "simple_chat", "complex_chat", "coding_request",
        "reasoning_request", "planning_request", "memory_query",
        "tool_request", "meta_request",
    ]

    # ---- Heuristic patterns (<1 ms) ----
    PATTERNS = {
        "simple_chat": [
            r"^(hi|hello|hey|thanks|bye|good morning|good night|how are you|what's up)\b",
        ],
        "memory_query": [
            r"(do you remember|what did I|recall|last time|have I told you)",
        ],
        "coding_request": [
            r"(write|code|function|class|debug|fix|refactor|implement|build|create a|make a)",
        ],
        "tool_request": [
            r"(read file|run command|search for|list files|git|execute|open)",
        ],
        "reasoning_request": [
            r"(explain why|reason|analyze|compare|evaluate|think about|what if)",
        ],
    }

    # MODEL_ROUTES will be dynamically resolved using MODELS_CONFIG below

    def __init__(self, model_router=None, classifier_model: str = None):
        self.model_router = model_router
        from models.config import MODELS_CONFIG
        self.classifier_model = classifier_model or MODELS_CONFIG["vision"]["name"]
        
        # Dynamically map intents to actual installed models configured in MODELS_CONFIG
        self.MODEL_ROUTES = {
            "simple_chat": MODELS_CONFIG["chat"]["name"],
            "complex_chat": MODELS_CONFIG["coding"]["name"],
            "coding_request": MODELS_CONFIG["coding"]["name"],
            "reasoning_request": MODELS_CONFIG["reasoning"]["name"],
            "planning_request": MODELS_CONFIG["chat"]["name"],
            "memory_query": MODELS_CONFIG["chat"]["name"],
            "tool_request": MODELS_CONFIG["chat"]["name"],
            "meta_request": MODELS_CONFIG["chat"]["name"],
        }

    async def process(self, context: ConversationContext) -> ConversationContext:
        intent = await self._detect(context.user_message)
        context.intent = intent
        context.model = self.MODEL_ROUTES.get(intent, "qwen3:14b")
        context.state.current_intent = intent
        context.state.last_model_used = context.model
        
        # Emit meta event immediately to the queue if present
        if context.event_queue is not None:
            context.event_queue.put_nowait({
                "type": "meta",
                "intent": context.intent,
                "model": context.model
            })
            
        return context

    async def _detect(self, message: str) -> str:
        """Heuristic-first. Falls back to LLM classification only when ambiguous."""
        # Phase 1: fast pattern match
        lower = message.lower().strip()
        for intent, patterns in self.PATTERNS.items():
            for pat in patterns:
                if re.search(pat, lower, re.IGNORECASE):
                    return intent

        # Phase 2: LLM fallback via Model Router
        if self.model_router is not None:
            return await self._llm_classify(message)

        return "simple_chat"

    async def _llm_classify(self, message: str) -> str:
        prompt = (
            "Classify the following user message into exactly one of these intents:\n"
            f"{', '.join(self.INTENTS)}\n\n"
            f"Message: '{message}'\n\n"
            "Output ONLY the intent name, nothing else."
        )
        try:
            response_text = await self.model_router.generate(
                task="classification",
                prompt=prompt,
                options={"temperature": 0.0},
            )
            response_text = response_text.strip()
            for intent in self.INTENTS:
                if intent in response_text:
                    return intent
        except Exception as e:
            logger.error("LLM intent classification failed: %s", e)

        return "simple_chat"
