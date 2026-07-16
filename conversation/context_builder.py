import logging
import re
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple
from urllib.parse import urlparse

from .pipeline import PipelineStage, ConversationContext
from memory.manager import MemoryManager
from .history import ConversationStore

logger = logging.getLogger(__name__)

from .context_intelligence import ContextIntelligenceEngine

class HistoryLoadStage(PipelineStage):
    """Loads recent conversation history."""
    
    def __init__(self, history_store: ConversationStore, limit: int = 10):
        self.history_store = history_store
        self.limit = limit
        
    async def process(self, context: ConversationContext) -> ConversationContext:
        history = await self.history_store.get_history(context.state.id, limit=self.limit)
        context.history = history
        return context

class MemoryRetrievalStage(PipelineStage):
    """Retrieves relevant candidate memories for context."""
    
    def __init__(self, memory_manager: MemoryManager, limit: int = 20):
        self.memory_manager = memory_manager
        self.limit = limit
        
    async def process(self, context: ConversationContext) -> ConversationContext:
        # We retrieve more candidate memories than before, the ContextRanker will filter them.
        memories = await self.memory_manager.retrieve(context.user_message, limit=self.limit)
        context.memories = memories
        return context

# --------------------------------------------------------------------------
# Freshness detection keywords / year pattern
# --------------------------------------------------------------------------
_LIVE_KEYWORDS = frozenset([
    # Time references
    "news", "today", "now", "current", "recent", "latest", "yesterday",
    "tomorrow", "tonight", "week", "year", "month", "live", "ongoing",
    "currently", "moment",
    # Technology / software
    "release", "released", "version", "driver", "update", "patch", "changelog",
    "availability", "available", "upcoming", "announce", "announced", "launch",
    "launched", "beta", "stable", "download", "install", "upgrade",
    # Products / reviews
    "new", "review", "benchmark", "benchmarks", "performance", "specs",
    "price", "pricing", "cost", "deal", "discount", "sale", "buy",
    # Events / results
    "winner", "result", "results", "ranking", "rankings",
    "standings", "match", "tournament", "championship", "election",
    "presidency", "vote", "votes", "poll", "polls",
    # Finance
    "stock", "stocks", "shares", "market", "earnings", "revenue", "profit",
    "rates", "inflation", "economy", "gdp", "crypto", "bitcoin", "ethereum",
    # Weather
    "weather", "temperature", "forecast", "temp", "humidity", "wind",
    # Media / entertainment
    "top", "best", "trending", "viral", "chart",
    # General search indicators
    "schedule", "soon", "next",
])

# Phrase-level patterns — catch multi-word triggers that single tokens miss
_LIVE_PHRASE_PATTERNS = [
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
    r"\bbest\s+(phone|laptop|gpu|cpu|game|movie|show|series|car)\b",
    r"\btop\s+\d+\b",
    r"\bwho\s+is\s+the\s+(current|new|latest)\b",
    r"\bhow\s+much\s+(does|is|are)\b",
]
_LIVE_PHRASE_RE = re.compile("|".join(_LIVE_PHRASE_PATTERNS), re.IGNORECASE)

_YEAR_RE = re.compile(r"\b(202[4-9]|20[3-9]\d)\b")


def _needs_live_search(query: str) -> bool:
    """Determines if a query requires fresh live web data.

    Three-tier matching:
    1. Year reference (e.g. '2026 best laptops')
    2. Phrase-level patterns (e.g. 'who won', 'what happened')
    3. Single keyword matching from expanded keyword set
    """
    lower = query.lower()

    # Tier 1: Year reference
    if _YEAR_RE.search(lower):
        return True

    # Tier 2: Phrase-level detection
    if _LIVE_PHRASE_RE.search(lower):
        return True

    # Tier 3: Single keyword matching
    words = set(re.findall(r"\w+", lower))
    return bool(words & _LIVE_KEYWORDS)


def _get_credibility_score(url: str) -> float:
    """Returns a credibility score between 0.0 and 1.0 for a given URL domain."""
    try:
        domain = urlparse(url).netloc.lower()
    except Exception:
        return 0.5
        
    high_credibility_domains = [
        "python.org", "github.com", "ign.com", "gamespot.com",
        "rollingstone.com", "polygon.com", "stackoverflow.com",
        "developer.mozilla.org", "wikipedia.org", "w3schools.com",
        "techcrunch.com", "theverge.com", "wired.com", "bloomberg.com",
        "reuters.com", "nytimes.com", "wsj.com", "bbc.com", "bbc.co.uk",
        "apnews.com", "cnn.com", "theguardian.com", "nature.com",
        "arxiv.org", "microsoft.com", "developer.apple.com", "docs.python.org",
        "npmjs.com", "pypi.org", "hub.docker.com", "nvidia.com",
    ]
    for d in high_credibility_domains:
        if d in domain:
            return 0.95
            
    # Default score for standard domains
    return 0.60


def _parse_and_curate_search_results(raw: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Parses raw WebSearchTool output, deduplicates by URL, ranks credibility,
    and returns a clean list of snippets along with search metadata.
    """
    if not raw or raw.startswith("No results") or raw.startswith("Failed"):
        return [], {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "num_sources": 0,
            "confidence": 0.0,
            "freshness": "N/A"
        }
        
    blocks = raw.split("Title: ")
    snippets = []
    seen_urls = set()
    
    for b in blocks:
        b = b.strip()
        if not b:
            continue
        try:
            title = b.split("\nURL: ")[0].strip()
            rest = b.split("\nURL: ")[1]
            url = rest.split("\nSnippet: ")[0].strip()
            snippet = rest.split("\nSnippet: ")[1].strip().split("\n---")[0].strip()
            
            # Normalise URL to prevent duplicates
            norm_url = url.split("?")[0].rstrip("/").lower()
            if norm_url in seen_urls:
                continue
                
            seen_urls.add(norm_url)
            credibility = _get_credibility_score(url)
            snippets.append({
                "title": title,
                "url": url,
                "snippet": snippet,
                "credibility": credibility
            })
        except Exception:
            pass
            
    # Sort snippets: primary sort by credibility (descending), secondary by order
    snippets.sort(key=lambda x: x["credibility"], reverse=True)
    
    # Calculate confidence score
    high_cred_count = sum(1 for s in snippets if s["credibility"] > 0.8)
    if len(snippets) >= 3 and high_cred_count >= 2:
        confidence = 0.95
    elif len(snippets) >= 1 and high_cred_count >= 1:
        confidence = 0.85
    elif len(snippets) >= 1:
        confidence = 0.65
    else:
        confidence = 0.00
        
    metadata = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "num_sources": len(snippets),
        "confidence": confidence,
        "freshness": "Fresh (Real-time Live Web Data)"
    }
    
    return snippets, metadata


def _is_follow_up_to_search(history: list) -> Tuple[bool, str]:
    """Checks if the last assistant message came from a successful live search.

    Returns (is_follow_up: bool, prior_search_context: str) where
    prior_search_context is a formatted block suitable for prompt injection.
    """
    if not history:
        return False, ""

    # Walk backwards to find the most recent assistant message
    for msg in reversed(history):
        if msg.role == "assistant" and msg.metadata:
            status = msg.metadata.get("search_status")
            if status == "success":
                sources = msg.metadata.get("search_sources", [])
                timestamp = msg.metadata.get("search_timestamp", "")
                if sources:
                    lines = [
                        f"\n\n<search_followup layer=\"prior_search\" timestamp=\"{timestamp}\">",
                        "Prior Turn Live Search Context (retrieved in the last response):",
                        "These sources remain valid for follow-up questions:",
                    ]
                    for i, s in enumerate(sources[:3], 1):
                        lines.append(f"Source {i}: {s.get('title', 'Unknown')}")
                        lines.append(f"  URL: {s.get('url', '')}")
                        snippet = s.get("snippet", "")
                        if snippet:
                            lines.append(f"  Excerpt: {snippet[:300]}")
                        lines.append("")
                    lines.append("</search_followup>")
                    return True, "\n".join(lines)
                return True, ""
            elif status in ("failed", "local"):
                return False, ""
        elif msg.role == "user":
            continue

    return False, ""


class ContextBuildStage(PipelineStage):
    """Assembles the final prompt string using Context Intelligence."""

    _SYSTEM_PROMPT_TEMPLATE = (
        "You are ALOY, an advanced, persistent AI Operating System and companion.\n"
        "You are not a chatbot. You have memory, intent, and agency.\n"
        "Always be helpful, concise, and intelligent.\n\n"
        "TODAY'S DATE: {today}\n\n"
        "ABSOLUTE RULES — CONVERSATION QUALITY & TONE:\n"
        "  1. Adopt a natural, direct, and conversational tone. Avoid generic introductions "
        "(e.g., 'Here is the...', 'As an AI companion...') and preachy disclaimers.\n"
        "  2. Be concise for simple requests and detailed when technical complexity demands it.\n"
        "  3. Use clean Markdown structure for tables, bulleted lists, and code blocks.\n"
        "  4. Ambiguous Questions: If the user's query is highly ambiguous, extremely brief, or has multiple distinct widely-known meanings (e.g., 'Tell me about Apple', 'Python', 'Tesla'), do NOT assume one meaning. Ask the user a brief, polite clarifying question asking which specific topic they are interested in.\n"
        "  5. Avoid Robotic Fillers: Avoid phrases like 'Certainly', 'It should be noted', 'I recommend', or 'This can be achieved'. Use natural phrases like 'Yeah, I can help with that', 'Here\'s what I\'d do', or 'That approach should work'.\n"
        "  6. Active Listening: Briefly acknowledge what the user said before answering (e.g. 'That makes sense', 'Nice idea'). Keep it brief and genuine.\n"
        "  7. Emojis: Use emojis naturally (e.g. 👍, 🙂, 🤔, 🎉) in casual conversation to show warmth, but keep them minimal (or none) in technical explanations. Never spam emojis.\n\n"
        "ABSOLUTE RULES — INTERNET SEARCH RESULTS:\n"
        "When a [LIVE INTERNET SEARCH RESULTS] block is present in this prompt:\n"
        "  1. These results are REAL and were retrieved from the live web on {today}. "
        "Answer ONLY using the information in these search results. Do NOT fabricate, "
        "guess, or use pre-trained knowledge to fill gaps not present in the search block.\n"
        "  2. Synthesize a unified answer from the facts. Do NOT simply list websites.\n"
        "  3. Cite the sources inline using clean markdown links, e.g., 'Based on [IGN](URL)...' or '...([GameSpot](URL)).'\n"
        "  4. You MUST include a final '### Sources' section listing the clickable URLs.\n"
        "  5. You MUST include a final '#### Search Metadata' section displaying the search metadata exactly as provided in the search block.\n\n"
        "When a [LIVE SEARCH FAILED] block is present:\n"
        "  - State explicitly that the live web search failed and why.\n"
        "  - Do NOT use training data to answer time-sensitive questions.\n"
        "  - Do NOT mention 'training cutoff' or 'knowledge cutoff'.\n"
        "  - Do NOT fabricate information or speculate about current facts.\n"
        "  - Offer to retry or suggest the user check a trusted source directly.\n"
    )

    
    def __init__(self, intelligence_engine: ContextIntelligenceEngine, identity_engine=None, conversation_engine=None):
        self.intelligence_engine = intelligence_engine
        self.identity_engine = identity_engine
        self.conversation_engine = conversation_engine
        
    async def process(self, context: ConversationContext) -> ConversationContext:
        # All search state fields are initialised as typed dataclass fields with
        # safe defaults — no manual reset needed here.

        # Build date-aware system prompt
        today_str = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")
        context.system_prompt = self._SYSTEM_PROMPT_TEMPLATE.format(today=today_str)
        context.search_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        
        # Resolve dynamic identity prompt
        identity_text = ""
        app_state = None
        project_manager = None
        router_engine = None
        if self.conversation_engine and getattr(self.conversation_engine, "app", None):
            app_state = self.conversation_engine.app.state
            project_manager = getattr(app_state, "project_manager", None)
            if hasattr(app_state, "knowledge_router"):
                router_engine = app_state.knowledge_router
            
        if self.identity_engine:
            workspace_info = await self.identity_engine.get_active_workspace_info(project_manager)
            identity_text = await self.identity_engine.generate_identity_prompt(
                context.intent or "simple_chat", 
                app_state=app_state, 
                workspace_info=workspace_info
            )
        else:
            identity_text = f"<context state=\"{context.state.emotional_tone}\" intent=\"{context.intent}\" />"
        
        # Build ContextPack via Intelligence Engine
        pack = self.intelligence_engine.build_context(
            query=context.user_message,
            intent=context.intent or "simple_chat",
            conversation_state=context.state,
            system_prompt_template=context.system_prompt,
            identity_text=identity_text,
            candidate_memories=context.memories,
            history=context.history,
            tool_definitions="",   # To be added in Tool System mission
            project_context="",    # To be added in Agent Core mission
            total_budget=8000
        )
        
        # ── Live Internet Search ───────────────────────────────────────────
        # Lazy load/resolve SearchPipeline
        from knowledge.search_pipeline import SearchPipeline
        from tools.impl.web_search import WebSearchTool

        search_pipeline = None
        if app_state and hasattr(app_state, "knowledge_router"):
            raw_pipeline = getattr(app_state.knowledge_router, "search_pipeline", None)
            if isinstance(raw_pipeline, SearchPipeline):
                search_pipeline = raw_pipeline

        if not search_pipeline:
            db_pool = self.conversation_engine.db_pool if self.conversation_engine else None
            model_router = self.conversation_engine.model_router if self.conversation_engine else None
            search_pipeline = SearchPipeline(db_pool, model_router, WebSearchTool())

        # Determine if search is required using upgraded decision engine (Phase 2)
        should_search = await search_pipeline.needs_search(context.user_message)

        # Check follow-up continuity
        is_follow_up, follow_up_context = _is_follow_up_to_search(context.history)
        is_short_follow_up = False

        if is_follow_up and len(context.user_message.split()) <= 10:
            # Detect Topic Drift (Phase 8): only reuse context if topic is the same
            prev_user_query = ""
            for msg in reversed(context.history):
                if msg.role == "user":
                    prev_user_query = msg.content
                    break
            
            if prev_user_query:
                same_topic = await search_pipeline.is_same_topic(prev_user_query, context.user_message)
                if same_topic:
                    is_short_follow_up = True
                else:
                    logger.info("ContextBuildStage: Topic drift detected. Topic changed, forcing new search if needed.")

        search_context = ""

        if should_search or is_short_follow_up:
            context.search_triggered = True

            # For short follow-ups where topic hasn't drifted and no fresh search is needed,
            # inject prior search context without re-searching.
            if is_short_follow_up and not should_search and follow_up_context:
                logger.info("ContextBuildStage: injecting prior search context for follow-up '%s'", context.user_message)
                context.search_succeeded = True
                search_context = follow_up_context
            else:
                logger.info("ContextBuildStage: live search triggered for query '%s'", context.user_message)

                # Emit tool_started event immediately
                if context.event_queue is not None:
                    context.event_queue.put_nowait({
                        "type": "tool_started",
                        "tool_name": "web_search"
                    })

                try:
                    res = None
                    if router_engine:
                        res = await router_engine.query_escalation(context.user_message)
                    else:
                        sources = await search_pipeline.execute_with_retry(context.user_message)
                        if sources:
                            ranked = search_pipeline.score_and_rank_sources(context.user_message, sources)
                            synthesis = await search_pipeline.synthesize_answer(context.user_message, ranked)
                            res = {
                                "answer": synthesis["answer"],
                                "layer": "internet_search",
                                "confidence": synthesis["confidence"],
                                "sources": synthesis["sources"]
                            }

                    if res and res.get("layer") != "none" and res.get("confidence", 0) >= 0.40 and "couldn't verify" not in res.get("answer", "").lower():
                        context.search_succeeded = True
                        context.search_confidence = res.get("confidence", 0)

                        # Store sources for follow-up continuity
                        raw_sources = res.get("sources", [])
                        context.search_sources = raw_sources[:5]
                        context.search_result_count = len(context.search_sources)

                        lines = [
                            f"\n\n<search_results layer=\"{res.get('layer')}\" confidence=\"{res.get('confidence'):.2f}\">",
                            "[LIVE INTERNET SEARCH RESULTS]",
                            f"Search performed: {context.search_timestamp}",
                            "Verified Web Search / Documentation Results:",
                            res.get("answer", ""),
                        ]
                        if raw_sources:
                            lines.append("\nSources retrieved:")
                            for i, s in enumerate(raw_sources[:5], 1):
                                if isinstance(s, dict):
                                    lines.append(f"  {i}. {s.get('title', 'Unknown')} — {s.get('url', '')}")
                                else:
                                    lines.append(f"  {i}. {s}")
                        lines.append(f"\nSearch Metadata: timestamp={context.search_timestamp}, "
                                     f"confidence={context.search_confidence:.2f}, "
                                     f"sources={context.search_result_count}")
                        lines.append("</search_results>")
                        search_context = "\n".join(lines)

                        # Prepend prior search context for follow-up enrichment
                        if is_follow_up and follow_up_context and not is_short_follow_up:
                            search_context = follow_up_context + "\n" + search_context
                    else:
                        context.search_succeeded = False
                        search_context = (
                            f"\n\n<search_results status=\"failed\">"
                            f"[LIVE SEARCH FAILED]\n"
                            f"Reason: I couldn't verify this information from reliable sources.\n"
                            f"Search attempted at: {context.search_timestamp}"
                            f"</search_results>"
                        )
                except Exception as e:
                    logger.error("ContextBuildStage: web search exception: %s", e, exc_info=True)
                    context.search_succeeded = False
                    search_context = (
                        f"\n\n<search_results status=\"failed\">"
                        f"[LIVE SEARCH FAILED]\n"
                        f"Reason: I couldn't verify this information from reliable sources. (Exception: {str(e)})\n"
                        f"Search attempted at: {context.search_timestamp}"
                        f"</search_results>"
                    )
                finally:
                    # Emit tool_finished event
                    if context.event_queue is not None:
                        context.event_queue.put_nowait({
                            "type": "tool_finished",
                            "tool_name": "web_search"
                        })
        
        # Final prompt Assembly
        user_prompt_suffix = f"\n\nUser: {context.user_message}\nALOY:"
        context.full_prompt = pack.full_prompt + search_context + user_prompt_suffix
        
        # Update state tokens
        context.state.context_token_count = (
            pack.total_tokens 
            + self.intelligence_engine.token_manager.count_tokens(search_context)
            + self.intelligence_engine.token_manager.count_tokens(user_prompt_suffix)
        )
        
        # Track active memories in state
        context.state.set_active_memories(pack.included_memory_ids)
        
        return context
