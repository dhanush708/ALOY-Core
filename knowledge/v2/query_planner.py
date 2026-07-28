"""
ALOY Search V2 — Query Planner

Deterministic, CPU-bound query normalization and variant planner. Transforms a
SearchIntent DTO into an optimized QueryPlan DTO without any LLM calls or network requests.
"""

import re
from typing import List, Set, Dict, Any, Optional

from knowledge.v2.models import SearchIntent, QueryPlan

# Patterns for comparative query extraction
_VS_PATTERN = re.compile(
    r"^(?:what\s+is\s+the\s+difference\s+between\s+|compare\s+)?(.*?)\s+(?:vs\.?|versus|compared\s+to|or|and)\s+(.*)$",
    re.IGNORECASE
)

_DIFF_PATTERN = re.compile(
    r"^difference\s+between\s+(.*?)\s+and\s+(.*)$",
    re.IGNORECASE
)


class QueryPlanner:
    """CPU-bound deterministic planner for query normalization and multi-query expansion."""

    def __init__(self, max_queries: int = 3):
        self.max_queries = max_queries

    def plan(self, intent: SearchIntent) -> QueryPlan:
        """Generate a deterministic QueryPlan from a SearchIntent DTO."""
        if not intent or not intent.query or not intent.query.strip():
            return QueryPlan(
                original_query="[empty]",
                queries=["[empty]"],
                strategy="single",
                required_providers=["duckduckgo"],
                max_results_per_query=5
            )

        norm_query = self._normalize_string(intent.query)
        if not norm_query:
            norm_query = "[empty]"

        # Check for comparative queries (X vs Y)
        variants, strategy = self._expand_variants(norm_query, intent.intent_type)

        # Deduplicate variants while preserving order
        unique_queries = self._deduplicate_queries(variants)
        final_queries = unique_queries[:self.max_queries]

        return QueryPlan(
            original_query=norm_query,
            queries=final_queries,
            strategy=strategy,
            required_providers=["duckduckgo"],
            max_results_per_query=5,
            metadata={
                "intent_type": intent.intent_type,
                "confidence": intent.confidence,
                "variant_count": len(final_queries)
            }
        )

    def _normalize_string(self, text: str) -> str:
        """Clean noise and collapse whitespace while preserving quoted and bracketed strings."""
        if not text:
            return ""

        # Collapse multiple spaces
        clean = re.sub(r"\s+", " ", text.strip())

        # Strip unneeded boundary noise punctuation (keep quotes, brackets, dashes, periods inside words)
        clean = re.sub(r"^[^\w\"\'\[\]]+|[^\w\"\'\[\]]+$", "", clean)
        return clean.strip()

    def _expand_variants(self, query: str, intent_type: str) -> tuple[List[str], str]:
        """Generate query variants for comparative queries or return single query."""
        if query == "[empty]":
            return ["[empty]"], "single"

        # 1. Comparative Query Detection
        diff_match = _DIFF_PATTERN.match(query)
        if diff_match:
            x, y = diff_match.group(1).strip(), diff_match.group(2).strip()
            if x and y:
                variants = [
                    f"{x} vs {y}",
                    f"compare {x} and {y}",
                    f"difference between {x} and {y}"
                ]
                return variants, "multi_hop"

        vs_match = _VS_PATTERN.match(query)
        if vs_match:
            x, y = vs_match.group(1).strip(), vs_match.group(2).strip()
            # Avoid matching single phrases if split is clean
            if x and y and len(x) > 1 and len(y) > 1 and not x.lower().startswith("what"):
                variants = [
                    f"{x} vs {y}",
                    f"compare {x} and {y}",
                    f"difference between {x} and {y}"
                ]
                return variants, "multi_hop"

        # 2. Standard Query Path
        strategy = "slow" if intent_type == "slow" else "single"
        return [query], strategy

    @staticmethod
    def _deduplicate_queries(queries: List[str]) -> List[str]:
        """Deduplicate query strings while preserving case and order."""
        seen: Set[str] = set()
        deduped: List[str] = []

        for q in queries:
            clean = q.strip()
            key = clean.lower()
            if clean and key not in seen:
                seen.add(key)
                deduped.append(clean)

        return deduped
