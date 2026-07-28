"""
Unit tests for ALOY Search V2 Decision Engine (knowledge/v2/decision_engine.py).
Target coverage: >90%. Pure CPU performance benchmarks included (< 2ms per request).
"""

import time
import pytest
from knowledge.v2.models import SearchIntent
from knowledge.v2.decision_engine import DecisionEngine


class TestDecisionEngine:

    def test_empty_and_whitespace_input(self):
        engine = DecisionEngine()
        res1 = engine.analyze("")
        res2 = engine.analyze("   ")

        assert res1.requires_search is False
        assert res1.intent_type == "none"
        assert res2.requires_search is False

    def test_explicit_year_reference_trigger(self):
        engine = DecisionEngine()
        intent = engine.analyze("best laptops in 2026")

        assert intent.requires_search is True
        assert intent.intent_type == "fast"
        assert intent.confidence == 1.0
        assert "year reference" in intent.reasoning.lower()

    def test_explicit_web_search_command(self):
        engine = DecisionEngine()
        intent = engine.analyze("search the web for python 3.14 changelog")

        assert intent.requires_search is True
        assert intent.intent_type == "fast"
        assert intent.confidence >= 0.95

    def test_time_sensitive_live_keywords(self):
        engine = DecisionEngine()

        news_intent = engine.analyze("latest news on quantum computing")
        weather_intent = engine.analyze("weather forecast today")
        stock_intent = engine.analyze("NVIDIA stock price")
        score_intent = engine.analyze("who won the match last night")

        assert news_intent.requires_search is True
        assert weather_intent.requires_search is True
        assert stock_intent.requires_search is True
        assert score_intent.requires_search is True

    def test_complex_comparative_query(self):
        engine = DecisionEngine()
        intent = engine.analyze("compare Claude 3.5 vs Gemini 1.5 Pro performance in 2026")

        assert intent.requires_search is True
        assert intent.intent_type == "slow"

    def test_followup_context_reuse(self):
        engine = DecisionEngine()

        # Followup query: short query when prior search succeeded
        intent = engine.analyze("what was the score?", prior_search_succeeded=True, prior_search_query="Super Bowl 2026")

        assert intent.requires_search is False
        assert intent.intent_type == "followup"
        assert intent.is_followup is True
        assert intent.confidence >= 0.95

    def test_non_search_greetings(self):
        engine = DecisionEngine()
        intent = engine.analyze("hello how are you today")

        assert intent.requires_search is False
        assert intent.intent_type == "none"

    def test_non_search_math(self):
        engine = DecisionEngine()
        intent = engine.analyze("125 * 84 + 3.14")

        assert intent.requires_search is False
        assert intent.intent_type == "none"

    def test_non_search_local_coding_and_writing(self):
        engine = DecisionEngine()
        code_intent = engine.analyze("write a python function to find prime numbers")
        write_intent = engine.analyze("format as markdown and fix grammar in this paragraph")

        assert code_intent.requires_search is False
        assert write_intent.requires_search is False

    def test_general_knowledge_fallback(self):
        engine = DecisionEngine()
        intent = engine.analyze("what is photosynthesis")

        assert intent.requires_search is False
        assert intent.intent_type == "none"
        assert intent.confidence == 0.70

    def test_performance_benchmark_under_2ms(self):
        """Verify 100 decisions run in < 200ms total (< 2ms per request)."""
        engine = DecisionEngine()
        queries = [
            "latest news on space exploration",
            "weather forecast for Tokyo tomorrow",
            "NVIDIA stock price today",
            "who won yesterday's football game",
            "compare iPhone 17 vs Samsung S26",
            "write a quicksort implementation in Python",
            "hello good morning",
            "what is the capital of France",
            "search online for Python 3.14 release notes",
            "100 + 45 * 2"
        ] * 10  # 100 queries total

        start_time = time.perf_counter()
        for q in queries:
            engine.analyze(q)
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        avg_ms_per_request = elapsed_ms / len(queries)
        assert avg_ms_per_request < 2.0, f"Decision engine took {avg_ms_per_request:.3f}ms per request (target < 2.0ms)"
