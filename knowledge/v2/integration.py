"""
ALOY Search V2 — Integration Adapter Layer

Thin integration gateway providing feature-flagged routing between Search V1
and Search V2, telemetry tracking, and automatic failover to Search V1 on
unexpected V2 errors.
"""

import os
import logging
import time
from typing import List, Dict, Any, Optional

from knowledge.v2.models import SearchContext, RankedEvidence
from knowledge.v2.providers.registry import ProviderRegistry
from knowledge.v2.providers.duckduckgo import DuckDuckGoProvider
from knowledge.v2.search_pipeline import SearchPipelineV2

logger = logging.getLogger(__name__)

# Default global feature flag setting
_ENV_FLAG = os.getenv("ALOY_USE_SEARCH_V2", "true").strip().lower()
_V2_ENABLED = _ENV_FLAG in ("true", "1", "yes", "on")

# Global Telemetry Counters
_METRICS = {
    "v2_requests": 0,
    "v2_successes": 0,
    "v2_avoided": 0,
    "v2_failures": 0,
    "v1_fallbacks": 0,
    "v1_requests": 0,
    "total_v2_latency_ms": 0.0,
    "total_evidence_retrieved": 0
}

# Singleton V2 pipeline instance
_GLOBAL_REGISTRY = ProviderRegistry()
_GLOBAL_REGISTRY.register(DuckDuckGoProvider(), enabled=True)
_GLOBAL_V2_PIPELINE = SearchPipelineV2(registry=_GLOBAL_REGISTRY)


def set_v2_enabled(enabled: bool) -> None:
    """Dynamically enable or disable Search V2 globally."""
    global _V2_ENABLED
    _V2_ENABLED = enabled
    logger.info(f"SearchIntegration: Search V2 feature flag set to {enabled}")


def is_v2_enabled() -> bool:
    """Check if Search V2 is currently enabled."""
    return _V2_ENABLED


def get_global_v2_pipeline() -> SearchPipelineV2:
    """Return the global Search V2 pipeline instance."""
    return _GLOBAL_V2_PIPELINE


def get_telemetry_metrics() -> Dict[str, Any]:
    """Return production telemetry metrics for Search V2 subsystem."""
    reqs = max(1, _METRICS["v2_requests"])
    avg_latency = round(_METRICS["total_v2_latency_ms"] / reqs, 2) if _METRICS["v2_requests"] > 0 else 0.0
    avoidance_rate = round((_METRICS["v2_avoided"] / reqs) * 100.0, 2) if _METRICS["v2_requests"] > 0 else 0.0
    avg_evidence = round(_METRICS["total_evidence_retrieved"] / max(1, _METRICS["v2_successes"]), 2) if _METRICS["v2_successes"] > 0 else 0.0

    return {
        "v2_enabled": _V2_ENABLED,
        "v2_requests": _METRICS["v2_requests"],
        "v2_successes": _METRICS["v2_successes"],
        "v2_avoided": _METRICS["v2_avoided"],
        "v2_failures": _METRICS["v2_failures"],
        "v1_fallbacks": _METRICS["v1_fallbacks"],
        "v1_requests": _METRICS["v1_requests"],
        "average_v2_latency_ms": avg_latency,
        "search_avoidance_rate_pct": avoidance_rate,
        "average_evidence_count": avg_evidence
    }


def reset_telemetry_metrics() -> None:
    """Reset telemetry counters (used during benchmarks/tests)."""
    for k in _METRICS:
        if isinstance(_METRICS[k], float):
            _METRICS[k] = 0.0
        else:
            _METRICS[k] = 0


class SearchIntegration:
    """Gateway router adapting caller requests between Search V1 and Search V2."""

    def __init__(self, v2_pipeline: Optional[SearchPipelineV2] = None):
        self.v2_pipeline = v2_pipeline or _GLOBAL_V2_PIPELINE

    async def execute_search(
        self,
        query: str,
        prior_search_succeeded: bool = False,
        prior_search_query: Optional[str] = None,
        v1_pipeline: Optional[Any] = None,
        provider_names: Optional[List[str]] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> SearchContext:
        """Execute search using V2 (if enabled) with automatic fallback to V1 on failure."""
        if is_v2_enabled():
            _METRICS["v2_requests"] += 1
            t0 = time.perf_counter()
            try:
                logger.debug(f"SearchIntegration: Invoking Search V2 for query '{query}'")
                context = await self.v2_pipeline.execute(
                    query=query,
                    prior_search_succeeded=prior_search_succeeded,
                    prior_search_query=prior_search_query,
                    provider_names=provider_names,
                    options=options
                )
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                _METRICS["total_v2_latency_ms"] += elapsed_ms

                if context and context.failure_reason != "system_error":
                    if not context.search_triggered:
                        _METRICS["v2_avoided"] += 1
                    elif context.search_succeeded:
                        _METRICS["v2_successes"] += 1
                        _METRICS["total_evidence_retrieved"] += context.results_count

                    return context

                _METRICS["v2_failures"] += 1
                _METRICS["v1_fallbacks"] += 1
                logger.warning(
                    f"SearchIntegration: Search V2 returned system_error for query '{query}'. Falling back to V1."
                )
            except Exception as e:
                _METRICS["v2_failures"] += 1
                _METRICS["v1_fallbacks"] += 1
                logger.error(
                    f"SearchIntegration: Unexpected error in Search V2 execution: {e}. Falling back to V1.",
                    exc_info=True
                )

        # Fallback to Search V1
        _METRICS["v1_requests"] += 1
        return await self._execute_v1_fallback(query, v1_pipeline)

    async def _execute_v1_fallback(self, query: str, v1_pipeline: Optional[Any]) -> SearchContext:
        """Execute legacy Search V1 pipeline and adapt output into a SearchContext DTO."""
        if not v1_pipeline:
            logger.info("SearchIntegration: No V1 pipeline instance available for fallback.")
            return SearchContext(
                search_triggered=False,
                search_succeeded=False,
                query=query,
                results_count=0,
                evidence=[],
                formatted_block="",
                failure_reason="v1_unavailable"
            )

        try:
            logger.info(f"SearchIntegration: Executing Search V1 fallback for query '{query}'")
            needs_search = await v1_pipeline.needs_search(query)
            if not needs_search:
                return SearchContext(
                    search_triggered=False,
                    search_succeeded=False,
                    query=query,
                    results_count=0,
                    evidence=[],
                    formatted_block="",
                    failure_reason=None
                )

            sources = await v1_pipeline.execute_with_retry(query)
            if not sources:
                return SearchContext(
                    search_triggered=True,
                    search_succeeded=False,
                    query=query,
                    results_count=0,
                    evidence=[],
                    formatted_block="[SEARCH RETURNED NO RESULTS]",
                    failure_reason="no_results"
                )

            ranked_sources = v1_pipeline.score_and_rank_sources(query, sources)

            evidence_list: List[RankedEvidence] = []
            for item in ranked_sources:
                if isinstance(item, dict):
                    evidence_list.append(
                        RankedEvidence(
                            title=item.get("title", ""),
                            url=item.get("url", ""),
                            snippet=item.get("snippet", ""),
                            score=float(item.get("score", 50.0)),
                            provider="duckduckgo"
                        )
                    )

            formatted_block = f"[LIVE INTERNET SEARCH RESULTS]\n" + "\n".join(
                f"- {e.title}: {e.snippet} ({e.url})" for e in evidence_list
            )

            return SearchContext(
                search_triggered=True,
                search_succeeded=True,
                query=query,
                results_count=len(evidence_list),
                evidence=evidence_list,
                formatted_block=formatted_block,
                confidence=0.80,
                failure_reason=None
            )
        except Exception as e:
            logger.error(f"SearchIntegration: V1 fallback search failed for query '{query}': {e}", exc_info=True)
            return SearchContext(
                search_triggered=True,
                search_succeeded=False,
                query=query,
                results_count=0,
                evidence=[],
                formatted_block="[SEARCH SYSTEM ERROR]",
                confidence=0.0,
                failure_reason="v1_execution_error"
            )
