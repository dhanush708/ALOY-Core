import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

@dataclass
class LearningCandidate:
    content: str
    type: str # 'observation', 'understanding', 'insight', 'procedural', 'mistake'
    confidence: float
    source_id: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
@dataclass
class LearningContext:
    conversation_id: str
    history: List[Dict[str, Any]]
    candidates: List[LearningCandidate] = field(default_factory=list)
    should_skip: bool = False
    skip_reason: str = ""
    extracted: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

class LearningPipelineStage:
    """Base class for all learning pipeline stages."""
    
    async def process(self, context: LearningContext) -> LearningContext:
        """Processes the learning context. Returns the modified context."""
        raise NotImplementedError
