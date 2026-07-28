import logging
import collections
from typing import Dict

logger = logging.getLogger(__name__)

class TokenBudgetManager:
    """Counts tokens and manages budget allocation."""
    
    def __init__(self):
        # We wrap tiktoken import so it degrades gracefully to a fallback strategy
        try:
            import tiktoken
            self._tokenizer = tiktoken.get_encoding("cl100k_base")
            self._has_tiktoken = True
            logger.debug("Tiktoken loaded successfully for token counting.")
        except ImportError:
            self._has_tiktoken = False
            logger.debug("Tiktoken not available. Using character-based token estimation.")
            
        self._token_cache = collections.OrderedDict()
        self._max_cache_size = 1024
            
    def count_tokens(self, text: str, model: str = None) -> int:
        """Count tokens for a given text."""
        if not text:
            return 0
            
        if text in self._token_cache:
            self._token_cache.move_to_end(text)
            return self._token_cache[text]
            
        if self._has_tiktoken:
            try:
                tokens = len(self._tokenizer.encode(text))
            except Exception as e:
                logger.warning(f"Tiktoken encode failed, falling back to estimation: {e}")
                tokens = max(1, int(len(text) / 4.0))
        else:
            # Fallback: roughly 4 chars per token
            tokens = max(1, int(len(text) / 4.0))
            
        self._token_cache[text] = tokens
        if len(self._token_cache) > self._max_cache_size:
            self._token_cache.popitem(last=False)
            
        return tokens
        
    def allocate_budget(self, total_budget: int, sections: Dict[str, int]) -> Dict[str, int]:
        """Allocate token budget across sections proportionally if sum exceeds total."""
        total_sections = sum(sections.values())
        if total_sections <= total_budget:
            return sections
            
        # Scale down proportionally
        scale = total_budget / total_sections
        return {k: int(v * scale) for k, v in sections.items()}
        
    def compress_to_budget(self, text: str, budget: int, strategy: str = 'truncate') -> str:
        """Compress text to fit within budget using specified strategy."""
        tokens = self.count_tokens(text)
        if tokens <= budget:
            return text
            
        # Target character budget (4 chars per token approximation)
        # Even with tiktoken, truncating by chars is safe and fast
        char_budget = max(0, budget * 4)
        
        if strategy == 'truncate':
            suffix = "... [truncated]"
            if char_budget <= len(suffix):
                return text[:char_budget]
            return text[:char_budget - len(suffix)] + suffix
            
        elif strategy == 'summarize':
            # Stub for real summarization. Currently falls back to truncation
            # because actual LLM summarization should be async and coordinated.
            suffix = "... [summarized]"
            if char_budget <= len(suffix):
                return text[:char_budget]
            return text[:char_budget - len(suffix)] + suffix
            
        else:
            return text[:char_budget]
