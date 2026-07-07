import logging
from typing import Optional
from models.router import ModelRouter

logger = logging.getLogger(__name__)


class AgentTriggerClassifier:
    """Classifies incoming user prompts to route them to Conversation, Knowledge, or Agent Runtime."""

    def __init__(self, model_router: Optional[ModelRouter] = None):
        self.model_router = model_router

    async def classify(self, text: str) -> str:
        """
        Classify text and return 'conversation', 'knowledge', or 'coding'.
        Uses heuristic matching and falls back to model-based classification.
        """
        text_lower = text.lower().strip()

        # Heuristic 1: Explicit instruction keywords
        coding_keywords = [
            "implement", "refactor", "write a python", "write code", "fix bug",
            "run tests", "create a function", "add file", "modify file",
            "build a feature", "code review", "debugging", "mission 11"
        ]
        if any(keyword in text_lower for keyword in coding_keywords):
            return "coding"

        knowledge_keywords = [
            "search the web", "look up on google", "current price of",
            "latest news on", "who won the", "find documentation for",
            "what is the latest version of"
        ]
        if any(keyword in text_lower for keyword in knowledge_keywords):
            return "knowledge"

        # Heuristic 2: Very short input
        if len(text.split()) < 4:
            return "conversation"

        # Fallback to Model Router if available
        if self.model_router:
            prompt = (
                "You are ALOY's trigger classifier. Categorize the user request into exactly one of these classes: "
                "conversation, knowledge, coding.\n\n"
                "Classes:\n"
                "- coding: Request to write, fix, refactor, test, or modify files in the codebase.\n"
                "- knowledge: Request for real-time, external, or documented information requiring a search engine.\n"
                "- conversation: Regular chit-chat, explaining concepts, general advice, or greetings.\n\n"
                f"User Request: \"{text}\"\n\n"
                "Respond with only the single word category name in lowercase (conversation, knowledge, or coding)."
            )
            try:
                res = await self.model_router.generate("classification", prompt)
                res_clean = res.strip().lower()
                for cat in ["coding", "knowledge", "conversation"]:
                    if cat in res_clean:
                        return cat
            except Exception as e:
                logger.warning("Classification model failed: %s. Falling back to conversation.", e)

        return "conversation"
