import logging
from typing import List, Dict, Any
from dataclasses import dataclass

from .state import ConversationState
from .token_manager import TokenBudgetManager
from .context_ranker import ContextRanker
from memory.types import ScoredMemory
from .history import ConversationMessage

logger = logging.getLogger(__name__)

@dataclass
class ContextPack:
    system_prompt: str
    identity_context: str
    memory_context: str
    history_context: str
    tool_context: str
    project_context: str
    total_tokens: int
    token_budget_remaining: int
    included_memory_ids: List[str]
    excluded_reasons: Dict[str, str]
    
    @property
    def full_prompt(self) -> str:
        """Assembles the final prompt string from components."""
        prompt_parts = []
        
        # System instructions
        if self.system_prompt:
            prompt_parts.append(f"<system>\n{self.system_prompt}\n</system>")
            
        # Identity
        if self.identity_context:
            prompt_parts.append(f"<identity>\n{self.identity_context}\n</identity>")
            
        # Memories
        if self.memory_context:
            prompt_parts.append(f"<memories>\n{self.memory_context}\n</memories>")
            
        # Tools
        if self.tool_context:
            prompt_parts.append(f"<tools>\n{self.tool_context}\n</tools>")
            
        # Project
        if self.project_context:
            prompt_parts.append(f"<project>\n{self.project_context}\n</project>")
            
        # History
        if self.history_context:
            prompt_parts.append(f"<history>\n{self.history_context}\n</history>")
            
        return "\n\n".join(prompt_parts)

class ContextIntelligenceEngine:
    """Dynamically composes optimal context for each query."""
    
    def __init__(self):
        self.token_manager = TokenBudgetManager()
        self.ranker = ContextRanker()
        self._context_cache = {}
        self._cache_keys_lru = []
        self._max_cache_size = 50
        
        # Profile definitions — history budgets increased for v1.0.2 continuity fix
        self.profiles = {
            'simple_chat': {
                'system': 300,
                'identity': 600,
                'memories': 1000,
                'history': 2000,
                'tools': 0,
                'project': 0,
                'reserve': 2000
            },
            'complex_chat': {
                'system': 300,
                'identity': 600,
                'memories': 2000,
                'history': 3000,
                'tools': 0,
                'project': 0,
                'reserve': 4000
            },
            'coding_request': {
                'system': 300,
                'identity': 600,
                'memories': 500,
                'history': 1500,
                'tools': 500,
                'project': 2000,
                'reserve': 4000
            },
            'memory_query': {
                'system': 300,
                'identity': 600,
                'memories': 3000,
                'history': 1500,
                'tools': 0,
                'project': 0,
                'reserve': 2000
            },
            'tool_request': {
                'system': 300,
                'identity': 600,
                'memories': 200,
                'history': 1500,
                'tools': 1500,
                'project': 500,
                'reserve': 2000
            },
            'reasoning_request': {
                'system': 300,
                'identity': 600,
                'memories': 1000,
                'history': 2000,
                'tools': 0,
                'project': 0,
                'reserve': 6000
            }
        }
        
    def get_profile(self, intent: str) -> Dict[str, int]:
        """Gets token budget profile for the given intent."""
        return self.profiles.get(intent, {
            'system': 300,
            'identity': 600,
            'memories': 1000,
            'history': 1000,
            'tools': 0,
            'project': 0,
            'reserve': 2000
        })
        
    def build_context(
        self,
        query: str,
        intent: str,
        conversation_state: ConversationState,
        system_prompt_template: str,
        identity_text: str,
        candidate_memories: List[ScoredMemory],
        history: List[ConversationMessage],
        tool_definitions: str = "",
        project_context: str = "",
        total_budget: int = 8000
    ) -> ContextPack:
        """
        Returns an optimized context composition.
        """
        # Caching logic
        mem_key = tuple((sm.memory.id, sm.memory.content, getattr(sm.memory, 'version', 1)) for sm in candidate_memories)
        hist_key = tuple((msg.role, msg.content) for msg in history if not (msg.content == query and msg.role == "user"))
        cache_key = (
            intent or "simple_chat",
            system_prompt_template,
            identity_text,
            mem_key,
            hist_key,
            tool_definitions,
            project_context,
            total_budget
        )
        
        if cache_key in self._context_cache:
            if cache_key in self._cache_keys_lru:
                self._cache_keys_lru.remove(cache_key)
            self._cache_keys_lru.append(cache_key)
            logger.debug("Context Pack Cache HIT")
            return self._context_cache[cache_key]
            
        logger.debug("Context Pack Cache MISS")

        # 1. Look up profile
        profile = self.get_profile(intent)
        
        # 2. Process system and identity
        system_tokens = self.token_manager.count_tokens(system_prompt_template)
        identity_tokens = self.token_manager.count_tokens(identity_text)
        
        if system_tokens > profile['system']:
            system_prompt = self.token_manager.compress_to_budget(system_prompt_template, profile['system'], 'truncate')
            system_tokens = self.token_manager.count_tokens(system_prompt)
        else:
            system_prompt = system_prompt_template
            
        if identity_tokens > profile['identity']:
            identity_context = self.token_manager.compress_to_budget(identity_text, profile['identity'], 'truncate')
            identity_tokens = self.token_manager.count_tokens(identity_context)
        else:
            identity_context = identity_text
            
        # 3. Pack tools and project context
        tool_tokens = 0
        tool_context = ""
        if profile['tools'] > 0 and tool_definitions:
            tool_context = self.token_manager.compress_to_budget(tool_definitions, profile['tools'], 'truncate')
            tool_tokens = self.token_manager.count_tokens(tool_context)
            
        proj_tokens = 0
        proj_context = ""
        if profile['project'] > 0 and project_context:
            proj_context = self.token_manager.compress_to_budget(project_context, profile['project'], 'truncate')
            proj_tokens = self.token_manager.count_tokens(proj_context)
            
        # 4. Rank candidate memories
        ranked_memories = self.ranker.rank_memories(candidate_memories, query, intent)
        
        # 5. Pack memories into memory budget
        mem_budget = profile['memories']
        included_memories = []
        included_memory_ids = []
        excluded_reasons = {}
        
        current_mem_tokens = 0
        for sm, final_score in ranked_memories:
            mem_text = f"- [{sm.memory.type}] {sm.memory.content}\n"
            mem_tokens = self.token_manager.count_tokens(mem_text)
            if current_mem_tokens + mem_tokens <= mem_budget:
                included_memories.append(mem_text)
                included_memory_ids.append(sm.memory.id)
                current_mem_tokens += mem_tokens
            else:
                excluded_reasons[sm.memory.id] = "Exceeded memory token budget for this intent profile"
                
        memory_context = "".join(included_memories).strip()
        
        # 6. Pack history into history budget (most recent first, so we reverse it, pack, then reverse back)
        hist_budget = profile['history']
        included_history_msgs = []
        current_hist_tokens = 0
        
        for msg in reversed(history):
            # Skip repeating the current user query if it's already in history
            if msg.content == query and msg.role == "user":
                continue
            msg_text = f"{msg.role.capitalize()}: {msg.content}\n"
            msg_tokens = self.token_manager.count_tokens(msg_text)
            if current_hist_tokens + msg_tokens <= hist_budget:
                included_history_msgs.insert(0, msg_text)
                current_hist_tokens += msg_tokens
            else:
                break
                
        history_context = "".join(included_history_msgs).strip()
        
        # 7. Calculate totals
        total_tokens = system_tokens + identity_tokens + current_mem_tokens + current_hist_tokens + tool_tokens + proj_tokens
        token_budget_remaining = total_budget - total_tokens - profile['reserve']
        
        # If we exceed total budget, we need to drop more from history then memories
        if total_tokens + profile['reserve'] > total_budget:
            excess_tokens = (total_tokens + profile['reserve']) - total_budget
            
            # Drop from history first (oldest first)
            while excess_tokens > 0 and included_history_msgs:
                removed_msg = included_history_msgs.pop(0)
                removed_tokens = self.token_manager.count_tokens(removed_msg)
                current_hist_tokens -= removed_tokens
                excess_tokens -= removed_tokens
                
            # If still excess, drop lowest ranked memories
            while excess_tokens > 0 and included_memories:
                removed_mem = included_memories.pop()
                removed_id = included_memory_ids.pop()
                removed_tokens = self.token_manager.count_tokens(removed_mem)
                current_mem_tokens -= removed_tokens
                excess_tokens -= removed_tokens
                excluded_reasons[removed_id] = "Dropped to meet total token budget"
                
            memory_context = "".join(included_memories).strip()
            history_context = "".join(included_history_msgs).strip()
            total_tokens = system_tokens + identity_tokens + current_mem_tokens + current_hist_tokens + tool_tokens + proj_tokens
            token_budget_remaining = total_budget - total_tokens - profile['reserve']
            
        pack = ContextPack(
            system_prompt=system_prompt,
            identity_context=identity_context,
            memory_context=memory_context,
            history_context=history_context,
            tool_context=tool_context,
            project_context=proj_context,
            total_tokens=total_tokens,
            token_budget_remaining=token_budget_remaining,
            included_memory_ids=included_memory_ids,
            excluded_reasons=excluded_reasons
        )
        
        # Cache the built pack
        self._context_cache[cache_key] = pack
        self._cache_keys_lru.append(cache_key)
        if len(self._cache_keys_lru) > self._max_cache_size:
            oldest = self._cache_keys_lru.pop(0)
            self._context_cache.pop(oldest, None)
            
        return pack
