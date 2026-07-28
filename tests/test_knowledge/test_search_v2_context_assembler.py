"""
Unit tests for ALOY Search V2 Context Assembler (knowledge/v2/context_assembler.py).
Target coverage: >90%. Pure CPU string formatting performance benchmark included.
"""

import time
import pytest
from knowledge.v2.models import RankedEvidence, SearchContext
from knowledge.v2.context_assembler import ContextAssembler


class TestContextAssembler:

    def test_empty_evidence_formatting(self):
        assembler = ContextAssembler()
        ctx = assembler.assemble("test query", [])

        assert ctx.search_triggered is True
        assert ctx.search_succeeded is False
        assert ctx.results_count == 0
        assert ctx.confidence == 0.0
        assert "[SEARCH RETURNED NO RESULTS]" in ctx.formatted_block
        assert 'query: "test query"' in ctx.formatted_block

    def test_single_evidence_formatting(self):
        assembler = ContextAssembler()
        ev = RankedEvidence(
            title="Python Release Notes",
            url="https://docs.python.org/3/whatsnew/3.14.html",
            snippet="Python 3.14 includes significant performance optimizations.",
            score=90.0
        )

        ctx = assembler.assemble("Python 3.14", [ev])

        assert ctx.search_succeeded is True
        assert ctx.results_count == 1
        assert ctx.confidence == 0.90
        assert "[LIVE INTERNET SEARCH RESULTS]" in ctx.formatted_block
        assert "Confidence: 90% (High)" in ctx.formatted_block
        assert "Python Release Notes" in ctx.formatted_block
        assert "https://docs.python.org/3/whatsnew/3.14.html" in ctx.formatted_block
        assert "Search Metadata: timestamp=" in ctx.formatted_block

    def test_multiple_evidence_order_preservation(self):
        assembler = ContextAssembler()
        ev1 = RankedEvidence(title="First Best Result", url="https://example.com/1", snippet="Snippet 1", score=95.0)
        ev2 = RankedEvidence(title="Second Best Result", url="https://example.com/2", snippet="Snippet 2", score=80.0)

        ctx = assembler.assemble("test query", [ev1, ev2])

        assert ctx.results_count == 2
        assert ctx.confidence == 0.88  # (95 + 80)/2 / 100 = 0.875 -> 0.88
        assert "Confidence: 87% (High)" in ctx.formatted_block or "Confidence: 88% (High)" in ctx.formatted_block

        first_pos = ctx.formatted_block.find("First Best Result")
        second_pos = ctx.formatted_block.find("Second Best Result")
        assert first_pos < second_pos

    def test_max_evidence_items_limiting(self):
        assembler = ContextAssembler(max_evidence_items=2)
        items = [
            RankedEvidence(title=f"Item {i}", url=f"https://e.com/{i}", snippet=f"Snippet {i}", score=100.0 - i * 10)
            for i in range(5)
        ]

        ctx = assembler.assemble("limiting test", items)

        assert ctx.results_count == 2
        assert len(ctx.evidence) == 2
        assert "Item 0" in ctx.formatted_block
        assert "Item 1" in ctx.formatted_block
        assert "Item 2" not in ctx.formatted_block

    def test_max_character_budget_truncation(self):
        assembler = ContextAssembler(max_characters=400)
        items = [
            RankedEvidence(
                title=f"Extremely Long Title For Article Number {i}",
                url=f"https://very-long-domain-name-example-{i}.org/deep/path/to/article",
                snippet=f"Detailed snippet content for item {i} explaining complex technical topics.",
                score=90.0 - i
            )
            for i in range(5)
        ]

        block = assembler.format_block("budget test", items)

        assert len(block) <= 400
        assert "[LIVE INTERNET SEARCH RESULTS]" in block

    def test_deterministic_output(self):
        assembler = ContextAssembler()
        ev = RankedEvidence(title="Deterministic Title", url="https://det.org", snippet="Det snippet", score=85.0)

        block1 = assembler.format_block("query", [ev], timestamp="2026-07-28 12:00:00 UTC")
        block2 = assembler.format_block("query", [ev], timestamp="2026-07-28 12:00:00 UTC")

        assert block1 == block2

    def test_performance_benchmark_under_5ms(self):
        """Verify context block generation completes in under 5ms CPU time."""
        assembler = ContextAssembler()
        items = [
            RankedEvidence(
                title=f"Benchmark Title {i}",
                url=f"https://benchmark.org/{i}",
                snippet=f"Benchmark snippet text for index {i}.",
                score=90.0 - i
            )
            for i in range(5)
        ]

        start_time = time.perf_counter()
        ctx = assembler.assemble("benchmark query", items, execution_time_ms=1.2)
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        assert ctx.search_succeeded is True
        assert elapsed_ms < 5.0, f"Context assembler took {elapsed_ms:.2f}ms (target < 5ms)"
