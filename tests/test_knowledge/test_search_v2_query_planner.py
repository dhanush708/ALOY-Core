"""
Unit tests for ALOY Search V2 Query Planner (knowledge/v2/query_planner.py).
Target coverage: >90%. Pure CPU performance benchmark included (< 5ms per request).
"""

import time
import pytest
from knowledge.v2.models import SearchIntent, QueryPlan
from knowledge.v2.query_planner import QueryPlanner


class TestQueryPlanner:

    def test_empty_search_intent_planning(self):
        planner = QueryPlanner()
        intent = SearchIntent(query="[empty]", requires_search=False)
        plan = planner.plan(intent)

        assert plan.original_query == "[empty]"
        assert plan.queries == ["[empty]"]
        assert plan.strategy == "single"
        assert plan.required_providers == ["duckduckgo"]

    def test_single_query_normalization(self):
        planner = QueryPlanner()
        intent = SearchIntent(query="   latest  NVIDIA   driver  updates...  ")
        plan = planner.plan(intent)

        assert plan.original_query == "latest NVIDIA driver updates"
        assert plan.queries == ["latest NVIDIA driver updates"]
        assert plan.strategy == "single"

    def test_quoted_phrase_preservation(self):
        planner = QueryPlanner()
        intent = SearchIntent(query='download "Python 3.14.0" binary')
        plan = planner.plan(intent)

        assert plan.original_query == 'download "Python 3.14.0" binary'
        assert plan.queries == ['download "Python 3.14.0" binary']

    def test_comparative_query_vs_expansion(self):
        planner = QueryPlanner()
        intent = SearchIntent(query="Python vs Rust", intent_type="slow")
        plan = planner.plan(intent)

        assert plan.original_query == "Python vs Rust"
        assert plan.strategy == "multi_hop"
        assert len(plan.queries) == 3
        assert "Python vs Rust" in plan.queries
        assert "compare Python and Rust" in plan.queries
        assert "difference between Python and Rust" in plan.queries

    def test_comparative_query_difference_between_expansion(self):
        planner = QueryPlanner()
        intent = SearchIntent(query="difference between Claude and ChatGPT", intent_type="slow")
        plan = planner.plan(intent)

        assert plan.strategy == "multi_hop"
        assert len(plan.queries) == 3
        assert "Claude vs ChatGPT" in plan.queries
        assert "compare Claude and ChatGPT" in plan.queries
        assert "difference between Claude and ChatGPT" in plan.queries

    def test_duplicate_query_variant_deduplication(self):
        planner = QueryPlanner()
        # Even if a match creates duplicate casing, planner deduplicates
        intent = SearchIntent(query="Python vs Python")
        plan = planner.plan(intent)

        assert len(plan.queries) <= 3
        assert len(plan.queries) == len(set(q.lower() for q in plan.queries))

    def test_slow_intent_strategy_selection(self):
        planner = QueryPlanner()
        intent = SearchIntent(query="complex architecture question", intent_type="slow")
        plan = planner.plan(intent)

        assert plan.strategy == "slow"

    def test_deterministic_output(self):
        planner = QueryPlanner()
        intent = SearchIntent(query="React vs Vue")

        plan1 = planner.plan(intent)
        plan2 = planner.plan(intent)

        assert plan1.queries == plan2.queries
        assert plan1.strategy == plan2.strategy

    def test_performance_benchmark_under_5ms(self):
        """Verify 100 query planning runs complete in < 500ms total (< 5ms per plan)."""
        planner = QueryPlanner()
        intents = [
            SearchIntent(query="Python vs Rust", intent_type="slow"),
            SearchIntent(query="latest NVIDIA driver 2026", intent_type="fast"),
            SearchIntent(query='download "Docker Desktop"', intent_type="fast"),
            SearchIntent(query="difference between PostgreSQL and MySQL", intent_type="slow"),
            SearchIntent(query="weather forecast today", intent_type="fast"),
        ] * 20  # 100 items total

        start_time = time.perf_counter()
        for i in intents:
            planner.plan(i)
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        avg_ms_per_plan = elapsed_ms / len(intents)
        assert avg_ms_per_plan < 5.0, f"Query planner took {avg_ms_per_plan:.3f}ms per plan (target < 5.0ms)"
