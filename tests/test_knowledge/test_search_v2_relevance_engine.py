"""
Unit tests for ALOY Search V2 Relevance Engine (knowledge/v2/relevance_engine.py).
Target coverage: >90%. Pure CPU performance benchmarks included. Zero internet dependency.
"""

import time
import pytest
from datetime import datetime, timezone
from knowledge.v2.models import NormalizedResult, RankedEvidence
from knowledge.v2.relevance_engine import RelevanceEngine


class TestRelevanceEngine:

    def test_empty_inputs_return_empty_list(self):
        engine = RelevanceEngine()
        res = NormalizedResult(title="Test", url="https://test.com", snippet="Test")

        assert engine.rank_and_slice("", [res]) == []
        assert engine.rank_and_slice("   ", [res]) == []
        assert engine.rank_and_slice("python", []) == []

    def test_duplicate_url_deduplication(self):
        engine = RelevanceEngine()
        r1 = NormalizedResult(title="Title 1", url="https://example.com/page?ref=1", snippet="Snippet 1")
        r2 = NormalizedResult(title="Title 2", url="https://example.com/page?ref=2", snippet="Snippet 2")
        r3 = NormalizedResult(title="Title 3", url="https://unique.org/page", snippet="Snippet 3")

        ranked = engine.rank_and_slice("test", [r1, r2, r3])

        # r1 and r2 have the same normalized URL (https://example.com/page)
        urls = [item.url for item in ranked]
        assert len(ranked) == 2
        assert "https://unique.org/page" in urls

    def test_extractive_sentence_slicing(self):
        engine = RelevanceEngine(max_top_sentences=1)
        snippet = (
            "This is random preamble. "
            "Python 3.14 includes significant performance optimizations for async execution. "
            "Another unrelated sentence here."
        )
        res = NormalizedResult(title="Python News", url="https://python.org", snippet=snippet)

        ranked = engine.rank_and_slice("Python 3.14 performance", [res])

        assert len(ranked) == 1
        assert "Python 3.14 includes significant performance optimizations" in ranked[0].snippet
        assert "random preamble" not in ranked[0].snippet

    def test_authority_scoring(self):
        engine = RelevanceEngine()

        official_res = NormalizedResult(title="Python", url="https://docs.python.org/3/", snippet="Official docs")
        news_res = NormalizedResult(title="Reuters", url="https://reuters.com/tech", snippet="News report")
        generic_res = NormalizedResult(title="Blog", url="https://randomblog.xyz", snippet="Generic post")

        ranked = engine.rank_and_slice("python", [official_res, news_res, generic_res])

        official_item = next(r for r in ranked if "python.org" in r.url)
        news_item = next(r for r in ranked if "reuters.com" in r.url)
        generic_item = next(r for r in ranked if "randomblog.xyz" in r.url)

        assert official_item.authority_score == 95.0
        assert news_item.authority_score == 96.0
        assert generic_item.authority_score == 50.0
        # Official source gets +15 bonus, giving it highest total score
        assert ranked[0].url == "https://docs.python.org/3/"

    def test_freshness_scoring(self):
        engine = RelevanceEngine()
        current_year = str(datetime.now(timezone.utc).year)

        fresh_res = NormalizedResult(
            title=f"Released in {current_year}",
            url="https://example.com/fresh",
            snippet=f"Latest update released in {current_year}"
        )
        old_res = NormalizedResult(
            title="Released in 2010",
            url="https://example.com/old",
            snippet="Legacy documentation from 2010"
        )

        ranked = engine.rank_and_slice("update", [fresh_res, old_res])

        fresh_item = next(r for r in ranked if "fresh" in r.url)
        old_item = next(r for r in ranked if "old" in r.url)

        assert fresh_item.freshness_score > old_item.freshness_score

    def test_html_tag_cleaning(self):
        engine = RelevanceEngine()
        raw_res = NormalizedResult(
            title="<b>Python</b> &amp; <i>Rust</i>",
            url="https://example.com",
            snippet="<p>Check out the &quot;latest&quot; news &lt;here&gt;.</p>"
        )

        ranked = engine.rank_and_slice("python rust", [raw_res])

        assert len(ranked) == 1
        assert ranked[0].title == "Python & Rust"
        assert ranked[0].snippet == 'Check out the "latest" news <here>.'

    def test_confidence_rating_assignment(self):
        engine = RelevanceEngine()
        high_res = NormalizedResult(title="Python Official", url="https://python.org", snippet="Python specs")
        ranked = engine.rank_and_slice("python specs", [high_res])

        assert ranked[0].score >= 85.0
        assert ranked[0].confidence_rating == "High"

    def test_deterministic_sorting(self):
        engine = RelevanceEngine()
        r1 = NormalizedResult(title="Alpha", url="https://blog.com/a", snippet="Python code")
        r2 = NormalizedResult(title="Beta", url="https://docs.python.org/b", snippet="Python code")

        ranked = engine.rank_and_slice("python", [r1, r2])

        # Docs source should be ranked first due to authority bonus
        assert ranked[0].title == "Beta"
        assert ranked[1].title == "Alpha"

    def test_performance_benchmark_under_50ms(self):
        """Verify processing 10 typical results completes in under 50ms CPU time."""
        engine = RelevanceEngine()

        sample_results = [
            NormalizedResult(
                title=f"Sample Search Result Title {i} - Python & Systems",
                url=f"https://domain-{i}.org/article-{i}",
                snippet=(
                    f"This is sentence 1 for article {i}. "
                    f"Python 3.14 performance benchmark details for index {i}. "
                    f"This is sentence 3 explaining additional features for index {i}."
                ),
                provider="duckduckgo"
            )
            for i in range(10)
        ]

        start_time = time.perf_counter()
        ranked = engine.rank_and_slice("Python 3.14 performance benchmark", sample_results, max_evidence=5)
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        assert len(ranked) == 5
        assert elapsed_ms < 50.0, f"Relevance engine took {elapsed_ms:.2f}ms (target < 50ms)"
