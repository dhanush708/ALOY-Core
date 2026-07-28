"""
ALOY Search V2 — Search Pipeline Orchestrator

Coordinates all Search V2 components (DecisionEngine, QueryPlanner, RetrievalLayer,
RelevanceEngine, ContextAssembler) into a clean, end-to-end workflow with total
exception isolation.
"""

import time
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from knowledge.v2.models import SearchContext, NormalizedResult
from knowledge.v2.providers.registry import ProviderRegistry
from knowledge.v2.decision_engine import DecisionEngine
from knowledge.v2.query_planner import QueryPlanner
from knowledge.v2.retrieval_layer import RetrievalLayer
from knowledge.v2.relevance_engine import RelevanceEngine
from knowledge.v2.context_assembler import ContextAssembler

logger = logging.getLogger(__name__)


class SearchPipelineV2:
    """Orchestrator tying together all Search V2 lifecycle modules."""

    def __init__(
        self,
        registry: ProviderRegistry,
        decision_engine: Optional[DecisionEngine] = None,
        query_planner: Optional[QueryPlanner] = None,
        retrieval_layer: Optional[RetrievalLayer] = None,
        relevance_engine: Optional[RelevanceEngine] = None,
        context_assembler: Optional[ContextAssembler] = None
    ):
        if not isinstance(registry, ProviderRegistry):
            raise TypeError(f"registry must be an instance of ProviderRegistry, got {type(registry)}")

        self.registry = registry
        self.decision_engine = decision_engine or DecisionEngine()
        self.query_planner = query_planner or QueryPlanner()
        self.retrieval_layer = retrieval_layer or RetrievalLayer(registry)
        self.relevance_engine = relevance_engine or RelevanceEngine()
        self.context_assembler = context_assembler or ContextAssembler()

    async def execute(
        self,
        query: str,
        prior_search_succeeded: bool = False,
        prior_search_query: Optional[str] = None,
        provider_names: Optional[List[str]] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> SearchContext:
        """Execute end-to-end Search V2 workflow and return SearchContext DTO."""
        start_time = time.perf_counter()

        try:
            # Stage 1: Decision Stage
            intent = self.decision_engine.analyze(
                query=query,
                prior_search_succeeded=prior_search_succeeded,
                prior_search_query=prior_search_query
            )

            if not intent.requires_search:
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                if intent.is_followup:
                    return SearchContext(
                        search_triggered=True,
                        search_succeeded=True,
                        query=query,
                        intent=intent,
                        results_count=0,
                        confidence=intent.confidence,
                        execution_time_ms=elapsed_ms,
                        formatted_block="",
                        failure_reason=None
                    )
                else:
                    return SearchContext(
                        search_triggered=False,
                        search_succeeded=False,
                        query=query,
                        intent=intent,
                        results_count=0,
                        confidence=intent.confidence,
                        execution_time_ms=elapsed_ms,
                        formatted_block="",
                        failure_reason=None
                    )

            # Stage 2: Query Planning Stage
            plan = self.query_planner.plan(intent)

            # Stage 3: Retrieval Stage across planned queries
            all_raw_results: List[NormalizedResult] = []
            target_providers = provider_names or plan.required_providers

            for q in plan.queries:
                raw_results = await self.retrieval_layer.retrieve(
                    query=q,
                    provider_names=target_providers,
                    options=options
                )
                all_raw_results.extend(raw_results)

            if not all_raw_results:
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                ctx = self.context_assembler.assemble(
                    query=query,
                    evidence=[],
                    execution_time_ms=elapsed_ms,
                    search_triggered=True
                )
                ctx.intent = intent
                ctx.plan = plan
                return ctx

            # Stage 4: Relevance & Ranking Stage
            ranked_evidence = self.relevance_engine.rank_and_slice(
                query=query,
                results=all_raw_results,
                max_evidence=5
            )

            # Stage 5: Context Assembly Stage
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            search_context = self.context_assembler.assemble(
                query=query,
                evidence=ranked_evidence,
                execution_time_ms=elapsed_ms,
                search_triggered=True
            )
            search_context.intent = intent
            search_context.plan = plan

            return search_context

        except Exception as e:
            logger.error(f"SearchPipelineV2: Pipeline execution failed for query '{query}': {e}", exc_info=True)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            return SearchContext(
                search_triggered=True,
                search_succeeded=False,
                query=query,
                results_count=0,
                evidence=[],
                formatted_block=(
                    f"[SEARCH SYSTEM ERROR]\n"
                    f"The search service encountered an unexpected error.\n"
                    f"Search attempted at: {ts}"
                ),
                confidence=0.0,
                execution_time_ms=elapsed_ms,
                failure_reason="system_error"
            )
