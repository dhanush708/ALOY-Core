"""
ALOY Search V2 — Relevance Engine

CPU-bound evidence ranking and extractive slicing engine. Transforms raw
NormalizedResult objects into scored, deduplicated, and sliced RankedEvidence
DTOs without any LLM calls or network operations.
"""

import re
import urllib.parse
from datetime import datetime, timezone
from typing import List, Set, Dict, Any

from knowledge.v2.models import NormalizedResult, RankedEvidence

# Stopwords set for fast keyword filtering
_STOP_WORDS = frozenset([
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "he",
    "in", "is", "it", "its", "of", "on", "that", "the", "to", "was", "were",
    "will", "with", "the", "this", "but", "they", "have", "had", "what", "when",
    "where", "who", "which", "why", "how", "can", "could", "should", "would"
])

# Domain authority mapping
_HIGH_AUTHORITY_OFFICIAL = frozenset([
    "python.org", "docs.python.org", "github.com", "nvidia.com", "microsoft.com",
    "developer.apple.com", "apple.com", "npmjs.com", "pypi.org", "hub.docker.com",
    "go.dev", "rust-lang.org"
])

_HIGH_AUTHORITY_NEWS = frozenset([
    "reuters.com", "bloomberg.com", "apnews.com", "nytimes.com", "wsj.com",
    "bbc.com", "bbc.co.uk", "theguardian.com"
])

_HIGH_AUTHORITY_KNOWLEDGE = frozenset([
    "wikipedia.org", "stackoverflow.com", "developer.mozilla.org", "w3schools.com"
])

_MEDIUM_AUTHORITY_TECH = frozenset([
    "techcrunch.com", "theverge.com", "wired.com", "ign.com", "gamespot.com",
    "polygon.com", "reddit.com"
])


class RelevanceEngine:
    """Fast, deterministic, CPU-bound ranking and sentence slicing engine."""

    def __init__(self, max_top_sentences: int = 3):
        self.max_top_sentences = max_top_sentences

    def rank_and_slice(
        self,
        query: str,
        results: List[NormalizedResult],
        max_evidence: int = 5
    ) -> List[RankedEvidence]:
        """Transform raw NormalizedResult DTOs into ranked and sliced RankedEvidence DTOs."""
        if not results or not query or not query.strip():
            return []

        query_terms = self._extract_query_terms(query)
        deduped_results = self._deduplicate_results(results)

        evidence_list: List[RankedEvidence] = []

        for res in deduped_results:
            clean_title = self._clean_html(res.title)
            raw_snippet = self._clean_html(res.snippet)

            if not clean_title and not raw_snippet:
                continue

            # Extractive CPU sentence slicing
            sliced_snippet = self._slice_relevant_sentences(query_terms, raw_snippet)

            # Compute scores
            domain = self._extract_domain(res.url)
            authority_score, official_bonus = self._score_authority(domain)
            freshness_score = self._score_freshness(clean_title + " " + raw_snippet)
            relevance_score = self._score_relevance(query_terms, clean_title, sliced_snippet)

            total_score = min(100.0, max(0.0, authority_score + freshness_score + relevance_score + official_bonus))

            evidence_list.append(
                RankedEvidence(
                    title=clean_title,
                    url=res.url,
                    snippet=sliced_snippet,
                    score=round(total_score, 2),
                    authority_score=round(authority_score, 2),
                    freshness_score=round(freshness_score, 2),
                    relevance_score=round(relevance_score, 2),
                    provider=res.provider,
                    timestamp=res.timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                )
            )

        # Deterministic sorting: primary by score descending, secondary by title
        evidence_list.sort(key=lambda x: (-x.score, x.title.lower()))

        return evidence_list[:max_evidence]

    def _deduplicate_results(self, results: List[NormalizedResult]) -> List[NormalizedResult]:
        """Remove duplicate results by normalized URL."""
        seen_urls: Set[str] = set()
        unique: List[NormalizedResult] = []

        for r in results:
            url = r.url or ""
            norm_url = url.split("?")[0].rstrip("/").lower()
            if norm_url and norm_url not in seen_urls:
                seen_urls.add(norm_url)
                unique.append(r)
            elif not norm_url:
                unique.append(r)

        return unique

    def _extract_query_terms(self, query: str) -> Set[str]:
        """Tokenize query into non-stopword lowercase terms."""
        words = set(re.findall(r"\w+", query.lower()))
        return words - _STOP_WORDS

    def _slice_relevant_sentences(self, query_terms: Set[str], text: str) -> str:
        """Extract top N sentences containing query terms."""
        if not text:
            return ""

        # Sentence tokenization via regex
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        if not sentences:
            return text.strip()

        if len(sentences) <= self.max_top_sentences:
            return " ".join(sentences)

        # Score sentences by keyword overlap
        scored_sentences = []
        for idx, sentence in enumerate(sentences):
            sent_words = set(re.findall(r"\w+", sentence.lower()))
            overlap = len(query_terms & sent_words)
            scored_sentences.append((overlap, -idx, sentence))

        # Sort by overlap descending, preserve original order on tie
        scored_sentences.sort(key=lambda x: (x[0], x[1]), reverse=True)
        top_sentences = [item[2] for item in scored_sentences[:self.max_top_sentences]]

        # Re-order top sentences to match original passage flow
        top_sentences_ordered = [s for s in sentences if s in top_sentences]
        return " ".join(top_sentences_ordered)

    def _score_authority(self, domain: str) -> tuple[float, float]:
        """Calculate domain authority score and official bonus."""
        if not domain:
            return 50.0, 0.0

        for d in _HIGH_AUTHORITY_OFFICIAL:
            if d in domain:
                return 95.0, 15.0

        for d in _HIGH_AUTHORITY_NEWS:
            if d in domain:
                return 96.0, 0.0

        for d in _HIGH_AUTHORITY_KNOWLEDGE:
            if d in domain:
                return 85.0, 0.0

        for d in _MEDIUM_AUTHORITY_TECH:
            if d in domain:
                return 75.0, 0.0

        return 50.0, 0.0

    def _score_freshness(self, text: str) -> float:
        """Calculate freshness score based on recent year mentions."""
        score = 0.0
        current_year = str(datetime.now(timezone.utc).year)
        last_year = str(datetime.now(timezone.utc).year - 1)
        next_year = str(datetime.now(timezone.utc).year + 1)

        text_lower = text.lower()
        if current_year in text_lower:
            score += 10.0
        if last_year in text_lower:
            score += 5.0
        if next_year in text_lower:
            score += 5.0

        return min(20.0, score)

    def _score_relevance(self, query_terms: Set[str], title: str, snippet: str) -> float:
        """Calculate term overlap relevance score."""
        if not query_terms:
            return 10.0

        content_words = set(re.findall(r"\w+", (title + " " + snippet).lower()))
        overlap = len(query_terms & content_words)

        return min(20.0, overlap * 4.0)

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract clean domain name from URL string."""
        if not url:
            return ""
        try:
            return urllib.parse.urlparse(url).netloc.lower()
        except Exception:
            return ""

    @staticmethod
    def _clean_html(text: str) -> str:
        """Strip HTML tags and unescape entities."""
        if not text:
            return ""
        clean = re.sub(r"<[^>]+>", "", text)
        clean = clean.replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'")
        return clean.strip()
