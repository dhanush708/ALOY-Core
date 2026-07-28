"""
ALOY Search V2 — Context Assembler

Converts ranked evidence DTOs into a deterministic, budget-enforced context
block string for prompt injection into the primary reasoning LLM.
"""

from datetime import datetime, timezone
from typing import List, Optional

from knowledge.v2.models import RankedEvidence, SearchContext


class ContextAssembler:
    """CPU-bound string formatting and budget enforcement engine for Search V2."""

    def __init__(self, max_evidence_items: int = 5, max_characters: int = 4000):
        self.max_evidence_items = max_evidence_items
        self.max_characters = max_characters

    def assemble(
        self,
        query: str,
        evidence: List[RankedEvidence],
        execution_time_ms: float = 0.0,
        search_triggered: bool = True
    ) -> SearchContext:
        """Assemble a complete SearchContext DTO from query and evidence."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        if not evidence:
            formatted_block = (
                f"[SEARCH RETURNED NO RESULTS]\n"
                f"The live search returned no matching results for query: \"{query}\"\n"
                f"Search attempted at: {timestamp}"
            )
            return SearchContext(
                search_triggered=search_triggered,
                search_succeeded=False,
                query=query,
                results_count=0,
                evidence=[],
                formatted_block=formatted_block,
                confidence=0.0,
                execution_time_ms=execution_time_ms,
                failure_reason="no_results"
            )

        # Enforce max evidence items count
        usable_evidence = sorted(evidence, key=lambda x: x.score, reverse=True)[:self.max_evidence_items]

        # Calculate overall confidence
        avg_score = sum(e.score for e in usable_evidence) / len(usable_evidence)
        overall_confidence = round(min(1.0, max(0.0, avg_score / 100.0)), 2)

        # Format prompt block
        formatted_block = self.format_block(query, usable_evidence, timestamp=timestamp, overall_confidence=overall_confidence)

        return SearchContext(
            search_triggered=search_triggered,
            search_succeeded=True,
            query=query,
            results_count=len(usable_evidence),
            evidence=usable_evidence,
            formatted_block=formatted_block,
            confidence=overall_confidence,
            execution_time_ms=execution_time_ms,
            failure_reason=None
        )

    def format_block(
        self,
        query: str,
        evidence: List[RankedEvidence],
        timestamp: Optional[str] = None,
        overall_confidence: float = 0.0
    ) -> str:
        """Generate deterministic prompt block string with budget enforcement."""
        if not evidence:
            ts = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            return (
                f"[SEARCH RETURNED NO RESULTS]\n"
                f"The live search returned no matching results for query: \"{query}\"\n"
                f"Search attempted at: {ts}"
            )

        ts = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        if overall_confidence == 0.0 and evidence:
            avg_score = sum(e.score for e in evidence) / len(evidence)
            overall_confidence = round(min(1.0, max(0.0, avg_score / 100.0)), 2)

        confidence_pct = int(overall_confidence * 100)
        overall_rating = "High" if overall_confidence >= 0.85 else ("Medium" if overall_confidence >= 0.60 else "Low")

        lines = [
            "[LIVE INTERNET SEARCH RESULTS]",
            f"Search performed: {ts}",
            f"Confidence: {confidence_pct}% ({overall_rating})",
            "",
            "Verified Web Search Results:"
        ]

        # Build evidence items
        items_lines = []
        for i, item in enumerate(evidence, 1):
            items_lines.append(f"  [{i}] {item.title}")
            if item.snippet:
                items_lines.append(f"      Excerpt: {item.snippet}")
            items_lines.append(f"      Source: {item.url}")
            items_lines.append("")

        # Build sources section
        sources_lines = ["Sources retrieved:"]
        for i, item in enumerate(evidence, 1):
            sources_lines.append(f"  {i}. {item.title} — {item.url}")

        metadata_line = f"\nSearch Metadata: timestamp={ts}, confidence={overall_confidence:.2f}, sources={len(evidence)}"

        # Combine into complete prompt text
        full_block = "\n".join(lines + items_lines + sources_lines) + metadata_line

        # Character budget truncation if necessary
        if len(full_block) > self.max_characters:
            full_block = self._truncate_to_budget(
                lines, evidence, sources_lines, metadata_line, ts, overall_confidence
            )

        return full_block

    def _truncate_to_budget(
        self,
        header_lines: List[str],
        evidence: List[RankedEvidence],
        sources_lines: List[str],
        metadata_line: str,
        timestamp: str,
        confidence: float
    ) -> str:
        """Progressively drop lowest-ranked evidence items until block fits under max_characters."""
        current_evidence = list(evidence)

        while len(current_evidence) > 1:
            current_evidence.pop()  # Drop lowest-ranked item

            items_lines = []
            for i, item in enumerate(current_evidence, 1):
                items_lines.append(f"  [{i}] {item.title}")
                if item.snippet:
                    items_lines.append(f"      Excerpt: {item.snippet}")
                items_lines.append(f"      Source: {item.url}")
                items_lines.append("")

            src_lines = ["Sources retrieved:"]
            for i, item in enumerate(current_evidence, 1):
                src_lines.append(f"  {i}. {item.title} — {item.url}")

            meta_line = f"\nSearch Metadata: timestamp={timestamp}, confidence={confidence:.2f}, sources={len(current_evidence)}"

            candidate_block = "\n".join(header_lines + items_lines + src_lines) + meta_line
            if len(candidate_block) <= self.max_characters:
                return candidate_block

        # If still over budget with 1 item, calculate snippet truncation
        item = current_evidence[0]
        base_items = [
            f"  [1] {item.title}",
            f"      Excerpt: ",
            f"      Source: {item.url}",
            ""
        ]
        src_lines = ["Sources retrieved:", f"  1. {item.title} — {item.url}"]
        meta_line = f"\nSearch Metadata: timestamp={timestamp}, confidence={confidence:.2f}, sources=1"

        base_len = len("\n".join(header_lines + base_items + src_lines) + meta_line)
        avail_snippet_len = max(10, self.max_characters - base_len - 5)
        truncated_snippet = item.snippet[:avail_snippet_len] + "..." if len(item.snippet) > avail_snippet_len else item.snippet

        base_items[1] = f"      Excerpt: {truncated_snippet}"

        final_block = "\n".join(header_lines + base_items + src_lines) + meta_line
        if len(final_block) > self.max_characters:
            final_block = final_block[:self.max_characters]
        return final_block
