"""
memory/profiles.py
------------------
Retrieval Profiles: pre-tuned retrieval configurations for different ALOY contexts.

Profiles:
  - conversation  : recency-biased, emotional context, broad types
  - coding        : importance-biased, code/fact types, workspace-scoped tags
  - planning      : importance + recency balanced, strategy/task types
  - learning      : importance-biased, insight/observation types
  - knowledge     : semantic-biased, fact/knowledge types, low recency weight
"""
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .retrieval import RetrievalEngine
    from .types import ScoredMemory

logger = logging.getLogger(__name__)


class RetrievalProfile(str, Enum):
    CONVERSATION = "conversation"
    CODING       = "coding"
    PLANNING     = "planning"
    LEARNING     = "learning"
    KNOWLEDGE    = "knowledge"


@dataclass
class ProfileConfig:
    """Weight overrides and filters for a retrieval profile."""
    # Scoring weights (must sum to ~1.0)
    w_semantic:    float = 0.50
    w_importance:  float = 0.25
    w_recency:     float = 0.25
    # Optional memory type filter
    types:         List[str] = field(default_factory=list)
    # Optional tag boosts — memories with these tags get a score multiplier
    tag_boosts:    List[str] = field(default_factory=list)
    tag_boost_factor: float = 1.15
    # Whether to include archived memories
    include_archived: bool = False
    # Default result limit
    default_limit: int = 10


_PROFILE_CONFIGS: dict[RetrievalProfile, ProfileConfig] = {
    RetrievalProfile.CONVERSATION: ProfileConfig(
        w_semantic=0.40,
        w_importance=0.20,
        w_recency=0.40,
        types=["observation", "emotion", "preference", "fact", "conversation"],
        tag_boosts=["personal", "preference", "context"],
    ),
    RetrievalProfile.CODING: ProfileConfig(
        w_semantic=0.50,
        w_importance=0.35,
        w_recency=0.15,
        types=["code", "fact", "procedure", "error", "fix", "strategy"],
        tag_boosts=["agent:fix", "agent:strategy", "agent:success", "code"],
        default_limit=12,
    ),
    RetrievalProfile.PLANNING: ProfileConfig(
        w_semantic=0.40,
        w_importance=0.35,
        w_recency=0.25,
        types=["goal", "strategy", "task", "plan", "decision"],
        tag_boosts=["agent:strategy", "planning"],
        default_limit=8,
    ),
    RetrievalProfile.LEARNING: ProfileConfig(
        w_semantic=0.35,
        w_importance=0.45,
        w_recency=0.20,
        types=["insight", "observation", "understanding", "lesson"],
        tag_boosts=["learning", "agent:success", "agent:failure"],
        default_limit=10,
    ),
    RetrievalProfile.KNOWLEDGE: ProfileConfig(
        w_semantic=0.60,
        w_importance=0.30,
        w_recency=0.10,
        types=["fact", "definition", "reference", "knowledge"],
        tag_boosts=["knowledge:verified", "verified"],
        default_limit=15,
    ),
}


class RetrievalProfileEngine:
    """
    Wraps the base RetrievalEngine with profile-aware query tuning.

    Uses the profile configuration to adjust scoring weights, apply tag boosts,
    and pre-filter by memory type.
    """

    def __init__(self, retrieval_engine: "RetrievalEngine", tag_manager=None):
        self._engine = retrieval_engine
        self._tags = tag_manager

    def get_config(self, profile: RetrievalProfile) -> ProfileConfig:
        return _PROFILE_CONFIGS[profile]

    async def retrieve(
        self,
        query: str,
        profile: RetrievalProfile,
        limit: Optional[int] = None,
        extra_tags: Optional[List[str]] = None,
        archived: bool = False,
    ) -> List["ScoredMemory"]:
        """
        Run a profile-tuned retrieval.

        Args:
            query:      The search query string.
            profile:    Which RetrievalProfile to apply.
            limit:      Override default result limit.
            extra_tags: Additional tags to filter by (ANDed with profile tag boosts).
            archived:   Whether to include archived memories.

        Returns:
            List of ScoredMemory ordered by profile-weighted score.
        """
        cfg = _PROFILE_CONFIGS[profile]
        effective_limit = limit or cfg.default_limit
        effective_types = cfg.types or None

        # Base retrieval (uses existing RRF pipeline)
        results = await self._engine.retrieve(
            query=query,
            types=effective_types,
            limit=effective_limit * 3,  # over-fetch for tag re-ranking
            archived=archived or cfg.include_archived,
        )

        # Apply tag boost if tag manager available
        if self._tags and cfg.tag_boosts:
            boost_set = set(cfg.tag_boosts + (extra_tags or []))
            for sm in results:
                mem_tags = set(self._tags.get_tags(sm.memory.id))
                if mem_tags & boost_set:
                    sm.score = min(1.0, sm.score * cfg.tag_boost_factor)

        # Re-sort after boost adjustments
        results.sort(key=lambda x: x.score, reverse=True)

        # Apply profile weight overrides to the score blend
        # (The base RetrievalEngine uses fixed weights; we adjust the final ordering
        # using the profile's w_semantic / w_importance / w_recency deltas.)
        if (cfg.w_semantic != 0.50 or cfg.w_importance != 0.25 or cfg.w_recency != 0.25):
            for sm in results:
                d = sm.relevance_details
                rrf        = d.get("rrf", sm.score)
                importance = d.get("importance", 0.5)
                recency    = d.get("recency", 0.5)
                sm.score = (
                    cfg.w_semantic   * rrf        +
                    cfg.w_importance * importance +
                    cfg.w_recency    * recency
                )
            results.sort(key=lambda x: x.score, reverse=True)

        return results[:effective_limit]
