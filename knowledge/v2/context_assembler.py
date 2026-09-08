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
        """Generate lightweight, conversational evidence block string with budget enforcement."""
        if not evidence:
            return ""

        ts = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        lines = [
            "[Context Information]",
            "The following verified live facts are available for TODAY'S DATE to inform your response. Integrate them naturally into your conversation as ALOY without sounding formal or corporate. Never state that you cannot browse real-time information or mention knowledge cutoffs.",
            ""
        ]

        for item in evidence:
            snippet_str = f": {item.snippet}" if item.snippet else ""
            lines.append(f"• {item.title}{snippet_str} (Source: {item.url})")

        full_block = "\n".join(lines)

        # Character budget truncation if necessary
        if len(full_block) > self.max_characters:
            full_block = self._truncate_to_budget(lines[:3], evidence)

        return full_block

    def _truncate_to_budget(
        self,
        header_lines: List[str],
        evidence: List[RankedEvidence]
    ) -> str:
        """Progressively drop lowest-ranked evidence items until block fits under max_characters."""
        current_evidence = list(evidence)

        while len(current_evidence) > 1:
            current_evidence.pop()

            lines = list(header_lines)
            for item in current_evidence:
                snippet_str = f": {item.snippet}" if item.snippet else ""
                lines.append(f"• {item.title}{snippet_str} (Source: {item.url})")

            candidate_block = "\n".join(lines)
            if len(candidate_block) <= self.max_characters:
                return candidate_block

        # If still over budget with 1 item, truncate snippet
        item = current_evidence[0]
        base_line = f"• {item.title} (Source: {item.url})"
        base_len = len("\n".join(header_lines + [base_line]))
        avail_snippet_len = max(10, self.max_characters - base_len - 15)
        truncated_snippet = item.snippet[:avail_snippet_len] + "..." if len(item.snippet) > avail_snippet_len else item.snippet

        final_line = f"• {item.title}: {truncated_snippet} (Source: {item.url})"
        final_block = "\n".join(header_lines + [final_line])

        if len(final_block) > self.max_characters:
            final_block = final_block[:self.max_characters]
        return final_block
