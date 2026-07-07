import logging
from typing import List, Optional

from .analyzer import EvolutionAnalyzer
from .gate import ReviewGate
from .proposal import ImprovementProposal

logger = logging.getLogger(__name__)


class EvolutionEngine:
    """Coordinates self-improvement scanning and user gate workflows."""

    def __init__(self, db_pool, memory_manager, model_router, model_tracker=None, prompt_registry=None, agent_runtime=None):
        self.db_pool = db_pool
        self.analyzer = EvolutionAnalyzer(db_pool, model_router, model_tracker)
        self.gate = ReviewGate(db_pool, memory_manager, prompt_registry, agent_runtime)

    async def start(self):
        logger.info("Evolution Engine starting...")

    async def stop(self):
        logger.info("Evolution Engine stopping...")

    async def run_scan(self) -> List[ImprovementProposal]:
        """Runs the issue detectors and LLM synthesis to draft pending proposals."""
        return await self.analyzer.scan_and_analyze()

    async def approve(self, proposal_id: str) -> bool:
        """Approve and apply a proposal."""
        return await self.gate.approve_proposal(proposal_id)

    async def reject(self, proposal_id: str) -> bool:
        """Reject a proposal."""
        return await self.gate.reject_proposal(proposal_id)

    async def get_proposals(self, status: Optional[str] = None) -> List[ImprovementProposal]:
        """Fetch all proposals from the database, optionally filtering by status."""
        query = "SELECT * FROM evolution_proposals"
        params = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC"

        proposals = []
        try:
            with self.db_pool.get_read_connection() as conn:
                cursor = conn.execute(query, params)
                rows = cursor.fetchall()
                for row in rows:
                    proposals.append(ImprovementProposal.from_row(row))
        except Exception as e:
            logger.error(f"Error fetching proposals: {e}")
        return proposals
