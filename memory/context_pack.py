"""
memory/context_pack.py
----------------------
ContextPackBuilder: assembles prompt-ready structured memory blocks for
efficient injection into LLM context windows.

Output is a ContextPack containing labelled text sections that the
Conversation Engine can concatenate directly into the prompt.
"""
import logging
from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .types import ScoredMemory, Memory
    from .profiles import RetrievalProfile

logger = logging.getLogger(__name__)

# Approximate chars per token (conservative estimate)
_CHARS_PER_TOKEN = 4


@dataclass
class ContextSection:
    label: str          # e.g. "Retrieved Memories", "Linked Context"
    content: str        # formatted text block
    token_estimate: int = 0
    source_ids: List[str] = field(default_factory=list)


@dataclass
class ContextPack:
    """
    A fully assembled, prompt-ready memory context block.

    Attributes:
        query:             The original query that produced this pack.
        sections:          Ordered list of ContextSection objects.
        total_tokens:      Estimated total token cost.
        token_budget_used: Fraction of the allowed budget consumed [0, 1].
        profile:           The retrieval profile used (string).
    """
    query: str
    sections: List[ContextSection] = field(default_factory=list)
    total_tokens: int = 0
    token_budget_used: float = 0.0
    profile: str = "conversation"

    def to_prompt_string(self) -> str:
        """Render all sections as a single prompt-insertable string."""
        parts = []
        for sec in self.sections:
            if sec.content.strip():
                parts.append(f"### {sec.label}\n{sec.content}")
        return "\n\n".join(parts)


class ContextPackBuilder:
    """
    Builds a ContextPack from a query by combining:
      1. Retrieved memories (profile-tuned)
      2. Linked / graph-neighbor memories
      3. Collection context (workspace scope)
      4. Working memory (ephemeral session items)

    Parameters
    ----------
    retrieval_engine  : The base RetrievalEngine (used directly for linked retrieval)
    profile_engine    : The RetrievalProfileEngine
    linker            : MemoryLinker (for graph traversal)
    collection_mgr    : CollectionManager
    tag_manager       : TagManager
    """

    def __init__(
        self,
        retrieval_engine,
        profile_engine,
        linker,
        collection_mgr,
        tag_manager,
    ):
        self._retrieval  = retrieval_engine
        self._profiles   = profile_engine
        self._linker     = linker
        self._collections = collection_mgr
        self._tags       = tag_manager
        from conversation.token_manager import TokenBudgetManager
        self.token_manager = TokenBudgetManager()

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_memories(memories: List["ScoredMemory"], max_items: int = 8) -> str:
        lines = []
        for i, sm in enumerate(memories[:max_items]):
            mem = sm.memory
            score_str = f"{sm.score:.2f}"
            tier = mem.tier
            content = mem.content[:300].replace("\n", " ")
            lines.append(f"[{i+1}] ({tier}, score={score_str}) {content}")
        return "\n".join(lines)

    @staticmethod
    def _format_plain(memories: List["Memory"], max_items: int = 5) -> str:
        lines = []
        for i, mem in enumerate(memories[:max_items]):
            content = mem.content[:200].replace("\n", " ")
            lines.append(f"[{i+1}] {content}")
        return "\n".join(lines)

    def _estimate_tokens(self, text: str) -> int:
        return self.token_manager.count_tokens(text)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def build(
        self,
        query: str,
        profile: "RetrievalProfile",
        workspace_id: Optional[str] = None,
        token_budget: int = 2000,
        seed_memory_id: Optional[str] = None,
    ) -> ContextPack:
        """
        Assemble a ContextPack for the given query and profile.

        Args:
            query:          The user's query or task description.
            profile:        RetrievalProfile to apply.
            workspace_id:   If provided, adds workspace-scoped collection context.
            token_budget:   Maximum estimated tokens across all sections.
            seed_memory_id: If provided, retrieve graph-linked neighbors from this memory.

        Returns:
            A fully populated ContextPack ready for prompt injection.
        """
        pack = ContextPack(query=query, profile=str(profile.value if hasattr(profile, "value") else profile))
        remaining = token_budget

        # ----------------------------------------------------------------
        # Section 1: Profile-tuned retrieval
        # ----------------------------------------------------------------
        try:
            retrieved = await self._profiles.retrieve(
                query=query,
                profile=profile,
                limit=8,
            )
            section_text = self._format_memories(retrieved)
            tokens = self._estimate_tokens(section_text)

            if section_text.strip() and tokens <= remaining:
                pack.sections.append(ContextSection(
                    label="Retrieved Memories",
                    content=section_text,
                    token_estimate=tokens,
                    source_ids=[sm.memory.id for sm in retrieved],
                ))
                remaining -= tokens
        except Exception as e:
            logger.warning(f"ContextPackBuilder: retrieval failed: {e}")

        # ----------------------------------------------------------------
        # Section 2: Graph-linked neighbors
        # ----------------------------------------------------------------
        if seed_memory_id and remaining > 100:
            try:
                linked = await self._linker.get_neighbors(seed_memory_id, max_hops=2)
                if linked:
                    section_text = self._format_plain(linked, max_items=5)
                    tokens = self._estimate_tokens(section_text)
                    if tokens <= remaining:
                        pack.sections.append(ContextSection(
                            label="Linked Context",
                            content=section_text,
                            token_estimate=tokens,
                            source_ids=[m.id for m in linked],
                        ))
                        remaining -= tokens
            except Exception as e:
                logger.warning(f"ContextPackBuilder: linked retrieval failed: {e}")

        # ----------------------------------------------------------------
        # Section 3: Workspace collection context
        # ----------------------------------------------------------------
        if workspace_id and remaining > 100:
            try:
                col = self._collections.find_or_create_workspace_collection(workspace_id)
                mem_ids = self._collections.list_memory_ids(col.id)[:10]
                if mem_ids:
                    # We just note the IDs; full hydration is expensive so we
                    # include a count summary.
                    section_text = (
                        f"Workspace '{workspace_id}' has {len(mem_ids)} remembered items "
                        f"in collection '{col.name}'."
                    )
                    tokens = self._estimate_tokens(section_text)
                    pack.sections.append(ContextSection(
                        label="Workspace Context",
                        content=section_text,
                        token_estimate=tokens,
                        source_ids=mem_ids,
                    ))
                    remaining -= tokens
            except Exception as e:
                logger.warning(f"ContextPackBuilder: workspace context failed: {e}")

        # ----------------------------------------------------------------
        # Finalise token accounting
        # ----------------------------------------------------------------
        total_used = sum(s.token_estimate for s in pack.sections)
        pack.total_tokens     = total_used
        pack.token_budget_used = round(total_used / token_budget, 3) if token_budget > 0 else 0.0

        return pack
