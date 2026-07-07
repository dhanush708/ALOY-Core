import logging
from typing import List, Tuple
from memory.types import ScoredMemory

logger = logging.getLogger(__name__)

class ContextRanker:
    """Scores and ranks context candidates by relevance to the query and intent."""
    
    def rank_memories(self, memories: List[ScoredMemory], query: str, intent: str) -> List[Tuple[ScoredMemory, float]]:
        """
        Ranks memories based on hybrid score, memory type relevance to intent,
        and temporal relevance.
        Returns a list of (memory, score) tuples, sorted highest score first.
        """
        ranked = []
        for m in memories:
            # Base score from hybrid search (combines FTS, similarity, recency, importance)
            base_score = m.score
            
            # Type boost based on intent
            type_boost = 1.0
            mem_type = m.memory.type
            
            if intent == 'coding_request':
                if mem_type in ['procedural', 'skill', 'project', 'task']:
                    type_boost = 1.5
                elif mem_type in ['preference', 'profile']:
                    type_boost = 1.1
                else:
                    type_boost = 0.5
            elif intent == 'memory_query':
                if mem_type in ['episodic', 'semantic', 'autobiographical']:
                    type_boost = 1.5
                else:
                    type_boost = 0.8
            elif intent == 'tool_request':
                if mem_type in ['tool', 'procedural']:
                    type_boost = 1.5
                else:
                    type_boost = 0.5
            elif intent == 'simple_chat':
                if mem_type in ['profile', 'preference', 'relationship']:
                    type_boost = 1.3
                else:
                    type_boost = 0.8
            
            final_score = base_score * type_boost
            ranked.append((m, final_score))
            
        # Sort descending by final score
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked
