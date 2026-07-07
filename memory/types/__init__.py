import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

@dataclass
class Memory:
    id: str
    type: str
    content: str
    tier: str = 'short_term'
    category: Optional[str] = None
    summary: Optional[str] = None
    source: Optional[str] = None
    source_id: Optional[str] = None
    confidence: float = 0.5
    importance: float = 0.5
    emotional_weight: float = 0.0
    access_count: int = 0
    last_accessed_at: Optional[str] = None
    decay_rate: float = 0.01
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    expires_at: Optional[str] = None
    archived_at: Optional[str] = None
    version: int = 1
    is_protected: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['metadata'] = json.dumps(d['metadata'])
        return d
        
    @classmethod
    def from_row(cls, row: dict) -> 'Memory':
        d = dict(row)
        if d.get('metadata'):
            try:
                d['metadata'] = json.loads(d['metadata'])
            except:
                d['metadata'] = {}
        else:
            d['metadata'] = {}
            
        # SQLite stores booleans as 0/1
        if 'is_protected' in d:
            d['is_protected'] = bool(d['is_protected'])
            
        return cls(**d)

@dataclass
class ScoredMemory:
    memory: Memory
    score: float
    relevance_details: Dict[str, float] = field(default_factory=dict)
