"""
Unit tests for ALOY Search V2 Models & DTOs (knowledge/v2/models.py).
Tests validation, default values, serialization, deserialization, and error handling.
"""

import pytest
from pydantic import ValidationError
from knowledge.v2.models import (
    SearchIntent,
    QueryPlan,
    NormalizedResult,
    RankedEvidence,
    SearchContext,
)


class TestSearchIntent:
    def test_valid_search_intent_defaults(self):
        intent = SearchIntent(query="Python 3.14 features")
        assert intent.query == "Python 3.14 features"
        assert intent.intent_type == "fast"
        assert intent.requires_search is True
        assert intent.is_followup is False
        assert intent.confidence == 1.0
        assert intent.reasoning is None
        assert intent.metadata == {}

    def test_search_intent_custom_values(self):
        intent = SearchIntent(
            query="who won the match yesterday?",
            intent_type="slow",
            requires_search=True,
            is_followup=True,
            confidence=0.85,
            reasoning="Sports result query requiring temporal search",
            metadata={"source": "heuristic_test"}
        )
        assert intent.intent_type == "slow"
        assert intent.is_followup is True
        assert intent.confidence == 0.85
        assert intent.reasoning == "Sports result query requiring temporal search"
        assert intent.metadata["source"] == "heuristic_test"

    def test_search_intent_empty_query_validation(self):
        with pytest.raises(ValidationError):
            SearchIntent(query="   ")

    def test_search_intent_invalid_confidence_range(self):
        with pytest.raises(ValidationError):
            SearchIntent(query="test", confidence=1.5)
        with pytest.raises(ValidationError):
            SearchIntent(query="test", confidence=-0.1)

    def test_search_intent_serialization(self):
        intent = SearchIntent(query="test query", reasoning="test reason")
        d = intent.to_dict()
        assert d["query"] == "test query"
        assert d["reasoning"] == "test reason"

        restored = SearchIntent.from_dict(d)
        assert restored.query == intent.query
        assert restored.reasoning == intent.reasoning


class TestQueryPlan:
    def test_query_plan_defaults(self):
        plan = QueryPlan(original_query="NVIDIA RTX 5090 launch date")
        assert plan.original_query == "NVIDIA RTX 5090 launch date"
        assert plan.queries == ["NVIDIA RTX 5090 launch date"]
        assert plan.strategy == "single"
        assert plan.required_providers == ["duckduckgo"]
        assert plan.max_results_per_query == 5

    def test_query_plan_empty_queries_fallback(self):
        plan = QueryPlan(original_query="clean prompt", queries=["", "  "])
        assert plan.queries == ["clean prompt"]

    def test_query_plan_invalid_max_results(self):
        with pytest.raises(ValidationError):
            QueryPlan(original_query="test", max_results_per_query=0)

    def test_query_plan_serialization(self):
        plan = QueryPlan(
            original_query="compare a and b",
            queries=["query a", "query b"],
            strategy="multi_hop",
            required_providers=["duckduckgo", "docs"]
        )
        d = plan.to_dict()
        assert d["strategy"] == "multi_hop"
        assert d["queries"] == ["query a", "query b"]

        restored = QueryPlan.from_dict(d)
        assert restored.strategy == plan.strategy
        assert restored.queries == plan.queries


class TestNormalizedResult:
    def test_normalized_result_defaults(self):
        res = NormalizedResult(
            title="Python Official Documentation",
            url="https://docs.python.org/3/",
            snippet="Python is an interpreted programming language."
        )
        assert res.title == "Python Official Documentation"
        assert res.provider == "unknown"
        assert res.raw_score == 0.0
        assert "UTC" in res.timestamp

    def test_normalized_result_serialization(self):
        res = NormalizedResult(
            title="Title",
            url="https://example.com",
            snippet="Snippet text",
            provider="duckduckgo",
            raw_score=95.0
        )
        d = res.to_dict()
        assert d["provider"] == "duckduckgo"
        assert d["raw_score"] == 95.0

        restored = NormalizedResult.from_dict(d)
        assert restored.url == res.url
        assert restored.raw_score == res.raw_score


class TestRankedEvidence:
    def test_ranked_evidence_defaults(self):
        ev = RankedEvidence(
            title="Tech Article",
            url="https://example.com/tech",
            snippet="Key excerpt",
            score=88.5
        )
        assert ev.score == 88.5
        assert ev.authority_score == 50.0
        assert ev.confidence_rating == "High"

    def test_ranked_evidence_confidence_validation(self):
        ev1 = RankedEvidence(confidence_rating="high")
        assert ev1.confidence_rating == "High"

        ev2 = RankedEvidence(confidence_rating="invalid_value")
        assert ev2.confidence_rating == "Medium"

    def test_ranked_evidence_score_bounds(self):
        with pytest.raises(ValidationError):
            RankedEvidence(score=105.0)
        with pytest.raises(ValidationError):
            RankedEvidence(score=-1.0)

    def test_ranked_evidence_serialization(self):
        ev = RankedEvidence(
            title="Test",
            url="https://test.com",
            snippet="Snippet",
            score=75.0,
            confidence_rating="Medium"
        )
        d = ev.to_dict()
        assert d["score"] == 75.0
        restored = RankedEvidence.from_dict(d)
        assert restored.score == ev.score


class TestSearchContext:
    def test_search_context_defaults(self):
        ctx = SearchContext()
        assert ctx.search_triggered is False
        assert ctx.search_succeeded is False
        assert ctx.results_count == 0
        assert ctx.evidence == []
        assert ctx.formatted_block == ""

    def test_search_context_nested_models(self):
        intent = SearchIntent(query="test query")
        plan = QueryPlan(original_query="test query")
        ev = RankedEvidence(title="Result", score=90.0)

        ctx = SearchContext(
            search_triggered=True,
            search_succeeded=True,
            query="test query",
            intent=intent,
            plan=plan,
            results_count=1,
            evidence=[ev],
            formatted_block="[VERIFIED EVIDENCE BLOCK]",
            confidence=0.90,
            execution_time_ms=1200.5
        )

        assert ctx.search_succeeded is True
        assert ctx.intent.query == "test query"
        assert ctx.plan.strategy == "single"
        assert len(ctx.evidence) == 1
        assert ctx.evidence[0].score == 90.0

        d = ctx.to_dict()
        assert d["intent"]["query"] == "test query"
        assert d["evidence"][0]["score"] == 90.0

        restored = SearchContext.from_dict(d)
        assert restored.intent.query == "test query"
        assert restored.evidence[0].score == 90.0
