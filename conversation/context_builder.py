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
    "news", "weather", "today", "now", "current", "release",
    "recent", "latest", "driver", "version",
    "released", "availability", "available", "best", "top",
    "new", "upcoming", "announce", "announced", "launch", "launched",
    "who", "what", "when", "winner", "score", "price", "stock",
    "update", "patch", "review",
])
_YEAR_RE = re.compile(r"\b(202[4-9]|20[3-9]\d)\b")


def _needs_live_search(query: str) -> bool:
    """Fast heuristic: does this query need fresh web data?"""
    lower = query.lower()
    if _YEAR_RE.search(lower):
        return True
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
        "reuters.com", "nytimes.com", "wsj.com"
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
        "  3. Use clean Markdown structure for tables, bulleted lists, and code blocks.\n\n"
        "ABSOLUTE RULES — INTERNET SEARCH RESULTS:\n"
        "When a [LIVE INTERNET SEARCH RESULTS] block is present in this prompt:\n"
        "  1. These results are REAL and were retrieved from the live web on {today}. "
        "Your training cutoff is irrelevant. The search results supercede it.\n"
        "  2. Synthesize a unified answer from the facts. Do NOT simply list websites.\n"
        "  3. Cite the sources inline using clean markdown links, e.g., 'Based on [IGN](URL)...' or '...([GameSpot](URL)).'\n"
        "  4. You MUST include a final '### Sources' section listing the clickable URLs.\n"
        "  5. You MUST include a final '#### Search Metadata' section displaying the search metadata exactly as provided in the search block.\n\n"
        "When a [LIVE SEARCH FAILED] block is present:\n"
        "  - State explicitly to the user that the live web search failed, along with the reason.\n"
        "  - Do NOT fabricate info or attempt to answer using potentially outdated model knowledge.\n"
    )
    
    def __init__(self, intelligence_engine: ContextIntelligenceEngine, identity_engine=None, conversation_engine=None):
        self.intelligence_engine = intelligence_engine
        self.identity_engine = identity_engine
        self.conversation_engine = conversation_engine
        
    async def process(self, context: ConversationContext) -> ConversationContext:
        # Build date-aware system prompt
        today_str = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")
        context.system_prompt = self._SYSTEM_PROMPT_TEMPLATE.format(today=today_str)
        
        # Resolve dynamic identity prompt
        identity_text = ""
        app_state = None
        project_manager = None
        if self.conversation_engine and getattr(self.conversation_engine, "app", None):
            app_state = self.conversation_engine.app.state
            project_manager = getattr(app_state, "project_manager", None)
            
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
        search_context = ""
        if _needs_live_search(context.user_message):
            logger.info("ContextBuildStage: live search triggered for query '%s'", context.user_message)
            
            # Emit tool_started event immediately
            if context.event_queue is not None:
                context.event_queue.put_nowait({
                    "type": "tool_started",
                    "tool_name": "web_search"
                })
                
            try:
                from tools.impl.web_search import WebSearchTool
                _search_tool = WebSearchTool()
                raw = await _search_tool.execute({"query": context.user_message}, {})
                logger.info("ContextBuildStage: raw search result length=%d", len(raw) if raw else 0)
                
                snippets, metadata = _parse_and_curate_search_results(raw)
                
                if snippets:
                    logger.info("ContextBuildStage: injecting %d curated search snippets", len(snippets))
                    
                    lines = [
                        f"\n\n[LIVE INTERNET SEARCH RESULTS — fetched {today_str}]",
                        f"Query searched: \"{context.user_message}\"",
                        "Use these facts to formulate your response. Cite urls naturally.\n",
                    ]
                    for i, s in enumerate(snippets, 1):
                        lines.append(f"Source {i}: {s['title']}")
                        lines.append(f"  URL: {s['url']}")
                        lines.append(f"  Credibility: {s['credibility']:.2f}")
                        lines.append(f"  Summary: {s['snippet']}")
                        lines.append("")
                        
                    lines.append("\n[SEARCH METADATA]")
                    lines.append(f"  Timestamp: {metadata['timestamp']}")
                    lines.append(f"  Number of Sources: {metadata['num_sources']}")
                    lines.append(f"  Confidence: {metadata['confidence']:.2f}")
                    lines.append(f"  Freshness: {metadata['freshness']}")
                    lines.append("[END OF SEARCH RESULTS]")
                    
                    search_context = "\n".join(lines)
                else:
                    raw_preview = (raw or "")[:200]
                    logger.warning("ContextBuildStage: search returned no parseable snippets. raw=%r", raw_preview)
                    search_context = (
                        f"\n\n[LIVE SEARCH FAILED]\n"
                        f"Live search returned no usable results for: '{context.user_message}'\n"
                        f"Reason: No results matched parser patterns.\n"
                        f"[END OF SEARCH ATTEMPT]"
                    )
            except Exception as e:
                logger.error("ContextBuildStage: web search exception: %s", e, exc_info=True)
                search_context = (
                    f"\n\n[LIVE SEARCH FAILED]\n"
                    f"Live search failed due to exception: {str(e)}\n"
                    f"[END OF SEARCH ATTEMPT]"
                )
            finally:
                # Emit tool_finished event immediately
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
