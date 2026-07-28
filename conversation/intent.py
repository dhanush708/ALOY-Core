import logging
import re
from typing import Optional

from .pipeline import PipelineStage, ConversationContext

logger = logging.getLogger(__name__)

# Import the search-trigger detector from context_builder so there is a single
# source of truth for what constitutes a live-search query.
# (Lazy import to avoid circular imports at module load time.)
def _import_needs_live_search():
    from .context_builder import _needs_live_search
    return _needs_live_search


class IntentDetectionStage(PipelineStage):
    """Classifies user intent — heuristic-first, LLM-fallback via Model Router."""

    INTENTS = [
        "simple_chat", "complex_chat", "coding_request",
        "reasoning_request", "planning_request", "memory_query",
        "tool_request", "meta_request", "live_search_query",
    ]

    # ---- Heuristic patterns (<1 ms) ----
    PATTERNS = {
        "simple_chat": [
            r"^(hi|hello|hey|thanks|bye|good morning|good night|how are you|what's up)\b",
            r"^(my name is|i am|i live|i work|my favorite|i like|i prefer)\b",
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
        "meta_request": [
            r"who\s+(are|built|created|made|programmed|owns)\s+(you|aloy|this)",
            r"what\s+version\s+are\s+you",
            r"what\s+model\s+(do|are)\s+you",
            r"are\s+you\s+(an\s+)?(chatgpt|gpt|phi|claude|gemini|llama|ai|bot|human)",
            r"what\s+makes\s+you\s+different",
            r"what\s+can\s+you\s+do",
            r"can\s+you\s+(access\s+my\s+files|read\s+my\s+files|see\s+my\s+files)",
            r"how\s+(are\s+you\s+different|do\s+you\s+compare)",
            r"describe\s+yourself",
            r"tell\s+me\s+about\s+yourself",
            r"your\s+(developer|purpose|architecture)",
            r"did\s+(google|openai|microsoft|meta|apple)\s+create\s+you",
            r"are\s+you\s+built\s+by",
            r"are\s+you\s+better\s+than",
            r"compared\s+to\s+(you|aloy|chatgpt|gpt|claude|gemini)"
        ],
    }

    def __init__(self, model_router=None, classifier_model: str = None):
        self.model_router = model_router
        from models.config import MODELS_CONFIG
        self.classifier_model = classifier_model or MODELS_CONFIG["vision"]["name"]

    async def process(self, context: ConversationContext) -> ConversationContext:
        # Check for manual overrides first
        if context.model_override == "reasoning":
            intent = "reasoning_request"
        elif context.model_override == "coding":
            intent = "coding_request"
        else:
            intent = await self._detect(context.user_message)
            
        context.intent = intent
        if self.model_router:
            context.model = self.model_router.resolve_model(intent, context.state.id)
        else:
            from models.config import MODELS_CONFIG
            context.model = MODELS_CONFIG["vision"]["name"]
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
        """Search-override first, then heuristic, then LLM fallback.
        
        CRITICAL: Live-search detection must run BEFORE any other classification
        because a query like "What's the latest score?" superficially looks like
        simple_chat but MUST trigger a live search.
        """
        # Phase 0.5: Meta-request pre-check
        # If the user is explicitly asking an identity/meta question, we bypass search override
        # so the system can answer from its internal identity prompt.
        lower = message.lower().strip()
        if "meta_request" in self.PATTERNS:
            for pattern in self.PATTERNS["meta_request"]:
                if re.search(pattern, lower, re.IGNORECASE):
                    logger.debug("IntentDetectionStage: matched meta_request pattern '%s'", pattern)
                    return "meta_request"

        # Phase 1: Pre-emptive search override — takes priority if not a meta request.
        # Import lazily to avoid circular dependency at module load.
        _needs_live_search = _import_needs_live_search()
        if _needs_live_search(message):
            logger.debug("IntentDetectionStage: pre-emptive live_search_query override for '%s'", message)
            return "live_search_query"

        # Phase 2: fast pattern match for remaining intents
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
            "CRITICAL RULES:\n"
            "- If the user is simply stating a fact about themselves (e.g., 'My name is Max', 'I like Python'), classify it as 'simple_chat'.\n"
            "- ONLY classify as 'memory_query' if the user is explicitly ASKING you to recall a memory (e.g., 'What is my name?', 'Do you remember...').\n\n"
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

