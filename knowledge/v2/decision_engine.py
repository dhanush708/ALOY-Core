"""
ALOY Search V2 — Decision Engine

Fast, deterministic, CPU-bound decision engine for classifying search intent.
Uses high-performance regex heuristics to determine whether a query requires
live search, context reuse, or local generation in < 2ms without LLM calls.
"""

import re
from typing import Optional, List, Dict, Any

from knowledge.v2.models import SearchIntent

# 1. Year Regex (e.g. 2026, 2027)
_YEAR_RE = re.compile(r"\b(202[4-9]|20[3-9]\d)\b")

# 2. Live Search Phrase Patterns
_LIVE_PHRASE_PATTERNS = [
    r"\b(search|look\s+up|google|find)\s+(the\s+web|online|internet|for)\b",
    r"\bwho\s+won\b",
    r"\bwhat\s+happened\b",
    r"\bwhat.s\s+the\s+latest\b",
    r"\bwhat.s\s+new\b",
    r"\bwhat\s+are\s+the\s+(latest|current|recent|best|top)\b",
    r"\bwhen\s+did\b",
    r"\bwhen\s+(is|was|will)\b",
    r"\bthis\s+(week|month|year|season)\b",
    r"\blast\s+(week|month|year|night|season)\b",
    r"\bright\s+now\b",
    r"\bat\s+the\s+moment\b",
    r"\bcoming\s+(soon|out|up)\b",
    r"\bjust\s+(released|announced|launched)\b",
    r"\blatest\s+version\s+of\b",
    r"\bbest\s+(phone|laptop|gpu|cpu|game|movie|show|series|car|tool|framework)\b",
    r"\btop\s+\d+\b",
    r"\bwho\s+is\s+the\s+(current|new|latest)\b",
    r"\bhow\s+much\s+(does|is|are)\b",
    r"\bstock\s+price\b",
    r"\bweather\s+(in|for|today|forecast)\b",
    r"\bscore\s+of\b",
]
_LIVE_PHRASE_RE = re.compile("|".join(_LIVE_PHRASE_PATTERNS), re.IGNORECASE)

# 3. Live Keywords Set
_LIVE_KEYWORDS = frozenset([
    "news", "today", "now", "current", "recent", "latest", "yesterday",
    "tomorrow", "tonight", "week", "year", "month", "live", "ongoing",
    "currently", "release", "released", "version", "driver", "update",
    "patch", "changelog", "availability", "available", "upcoming", "announce",
    "announced", "launch", "launched", "beta", "stable", "download",
    "install", "upgrade", "benchmark", "benchmarks", "performance", "specs",
    "price", "pricing", "cost", "deal", "discount", "sale", "winner",
    "result", "results", "ranking", "rankings", "standings", "match",
    "championship", "election", "vote", "poll", "stock", "stocks", "shares",
    "market", "earnings", "revenue", "profit", "inflation", "gdp", "crypto",
    "bitcoin", "ethereum", "weather", "forecast", "temp", "temperature",
    "humidity", "trending", "viral", "ceo", "president"
])

# 4. Complex Query Multi-hop Indicators
_COMPLEX_QUERY_PATTERNS = [
    r"\bcompare\b",
    r"\bversus\b",
    r"\bvs\.?\b",
    r"\bdifference\s+between\b",
    r"\bpros\s+and\s+cons\b",
    r"\bwhich\s+is\s+(better|faster|cheaper|stronger)\b"
]
_COMPLEX_QUERY_RE = re.compile("|".join(_COMPLEX_QUERY_PATTERNS), re.IGNORECASE)

# 5. Non-Search / Local Execution Patterns
_GREETING_RE = re.compile(
    r"^(hi|hello|hey|greetings|good\s+morning|good\s+afternoon|good\s+night|howdy|thanks|thank\s+you|bye|goodbye)\b",
    re.IGNORECASE
)

_LOCAL_TASK_RE = re.compile(
    r"\b(write\s+a\s+(python|js|script|function|class)|refactor|debug\s+this|fix\s+this|format\s+as|proofread|summarize\s+this|translate|rephrase|rewrite)\b",
    re.IGNORECASE
)

_MATH_RE = re.compile(r"^\s*(\d+[\s\+\-\*\/\^\(\)\.]*)+$")


class DecisionEngine:
    """CPU-bound decision engine for classifying search intents in < 2ms."""

    def analyze(
        self,
        query: str,
        prior_search_succeeded: bool = False,
        prior_search_query: Optional[str] = None
    ) -> SearchIntent:
        """Classify a user query and return a SearchIntent DTO."""
        if not query or not query.strip():
            return SearchIntent(
                query="[empty]",
                intent_type="none",
                requires_search=False,
                confidence=1.0,
                reasoning="Empty or whitespace query"
            )

        clean_query = query.strip()
        lower_query = clean_query.lower()

        # 1. Non-Search Patterns Pre-check (Greetings, Math, Local Tasks)
        if _GREETING_RE.match(lower_query):
            return SearchIntent(
                query=clean_query,
                intent_type="none",
                requires_search=False,
                confidence=0.98,
                reasoning="Casual greeting query"
            )

        if _MATH_RE.match(clean_query):
            return SearchIntent(
                query=clean_query,
                intent_type="none",
                requires_search=False,
                confidence=1.0,
                reasoning="Pure mathematical expression"
            )

        if _LOCAL_TASK_RE.search(lower_query):
            return SearchIntent(
                query=clean_query,
                intent_type="none",
                requires_search=False,
                confidence=0.90,
                reasoning="Local code generation or text processing task"
            )

        # 2. Check for Short Follow-Up Query
        if prior_search_succeeded and len(clean_query.split()) <= 6:
            if not _YEAR_RE.search(lower_query) and not any(k in lower_query for k in ("news", "today", "weather")):
                return SearchIntent(
                    query=clean_query,
                    intent_type="followup",
                    requires_search=False,
                    is_followup=True,
                    confidence=0.95,
                    reasoning="Short follow-up query reusing prior search context",
                    metadata={"prior_query": prior_search_query or ""}
                )

        # Helper to pick intent_type ("slow" if complex multi-hop, else "fast")
        is_complex = bool(_COMPLEX_QUERY_RE.search(lower_query))
        intent_type = "slow" if is_complex else "fast"

        # 3. Explicit / Heuristic Live Search Triggers
        if _YEAR_RE.search(lower_query):
            return SearchIntent(
                query=clean_query,
                intent_type=intent_type,
                requires_search=True,
                confidence=1.0,
                reasoning="Explicit year reference detected"
            )

        if _LIVE_PHRASE_RE.search(lower_query):
            return SearchIntent(
                query=clean_query,
                intent_type=intent_type,
                requires_search=True,
                confidence=0.95,
                reasoning="Live search phrase pattern matched"
            )

        words = set(re.findall(r"\w+", lower_query))
        matched_keywords = words & _LIVE_KEYWORDS
        if matched_keywords:
            return SearchIntent(
                query=clean_query,
                intent_type=intent_type,
                requires_search=True,
                confidence=0.90,
                reasoning=f"Time-sensitive keywords matched: {', '.join(sorted(matched_keywords)[:3])}"
            )

        # 4. Default Fallback
        return SearchIntent(
            query=clean_query,
            intent_type="none",
            requires_search=False,
            confidence=0.70,
            reasoning="General knowledge query answerable without search"
        )
