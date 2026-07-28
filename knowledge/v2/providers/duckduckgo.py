"""
ALOY Search V2 — DuckDuckGo Provider

Production implementation of ISearchProvider using DuckDuckGo HTML interface.
Reuses proven V1 HTML scraping and regex parsing logic, outputting structured
NormalizedResult DTOs.
"""

import asyncio
import logging
import re
import urllib.parse
import urllib.request
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from knowledge.v2.interfaces import ISearchProvider
from knowledge.v2.models import NormalizedResult

logger = logging.getLogger(__name__)

# Primary DDG Result Pattern (proven V1 regex)
_PRIMARY_PATTERN = re.compile(
    r'<div class="[^"]*web-result[^"]*">.*?'
    r'<a[^>]*class="result__a"[^>]*href="(?P<url>[^"]*)"[^>]*>(?P<title>.*?)</a>.*?'
    r'<a[^>]*class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
    re.DOTALL
)

# Secondary Fallback Patterns (proven V1 regex)
_SNIPPET_PATTERN = re.compile(r'<a[^>]*class="result__snippet[^"]*"[^>]*>(.*?)</a>', re.DOTALL)
_URL_PATTERN = re.compile(r'<a[^>]*class="result__url"[^>]*href="(?P<url>[^"]*)"[^>]*>(.*?)</a>', re.DOTALL)
_TITLE_PATTERN = re.compile(r'<a[^>]*class="result__a"[^>]*>(.*?)</a>', re.DOTALL)


class DuckDuckGoProvider(ISearchProvider):
    """DuckDuckGo web search provider using HTML scraping."""

    def __init__(self, timeout_seconds: float = 7.0):
        self._timeout = timeout_seconds

    @property
    def name(self) -> str:
        return "duckduckgo"

    @property
    def capabilities(self) -> List[str]:
        return ["web", "search"]

    async def is_available(self) -> bool:
        """DuckDuckGo HTML interface requires no API key."""
        return True

    async def execute(
        self,
        query: str,
        options: Optional[Dict[str, Any]] = None
    ) -> List[NormalizedResult]:
        """Execute a DuckDuckGo web search query and return normalized results."""
        if not query or not query.strip():
            return []

        options = options or {}
        max_results = options.get("max_results", 6)

        query_encoded = urllib.parse.quote_plus(query.strip())
        url = f"https://html.duckduckgo.com/html/?q={query_encoded}"

        loop = asyncio.get_running_loop()

        def _fetch() -> str:
            req = urllib.request.Request(
                url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                }
            )
            with urllib.request.urlopen(req, timeout=6) as response:
                return response.read().decode('utf-8', errors='replace')

        try:
            html = await asyncio.wait_for(
                loop.run_in_executor(None, _fetch),
                timeout=self._timeout
            )
            return self._parse_html(html, max_results=max_results)
        except asyncio.TimeoutError:
            logger.warning(f"DuckDuckGo search timed out after {self._timeout}s for query '{query}'")
            return []
        except Exception as e:
            logger.error(f"DuckDuckGo search failed for query '{query}': {e}")
            return []

    def _parse_html(self, html: str, max_results: int = 6) -> List[NormalizedResult]:
        """Parse raw DuckDuckGo HTML using proven V1 primary and secondary regex parsers."""
        if not html or not html.strip():
            return []

        results: List[NormalizedResult] = []

        matches = list(_PRIMARY_PATTERN.finditer(html))
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        if matches:
            for m in matches[:max_results]:
                title = re.sub(r'<[^>]+>', '', m.group("title")).strip()
                raw_url = m.group("url")
                url = self._clean_url(raw_url)
                snippet = re.sub(r'<[^>]+>', '', m.group("snippet")).strip()

                if title and url:
                    results.append(
                        NormalizedResult(
                            title=title,
                            url=url,
                            snippet=snippet,
                            provider=self.name,
                            timestamp=now_str
                        )
                    )
        else:
            # Fallback parsing strategy from V1
            t_matches = _TITLE_PATTERN.findall(html)
            u_matches = _URL_PATTERN.findall(html)
            s_matches = _SNIPPET_PATTERN.findall(html)

            count = min(len(t_matches), len(u_matches), len(s_matches), max_results)
            for i in range(count):
                title = re.sub(r'<[^>]+>', '', t_matches[i]).strip()
                raw_url_val = u_matches[i][0] if isinstance(u_matches[i], tuple) else u_matches[i]
                url = self._clean_url(raw_url_val.strip())
                snippet_val = s_matches[i][0] if isinstance(s_matches[i], tuple) else s_matches[i]
                snippet = re.sub(r'<[^>]+>', '', snippet_val).strip()

                if title and url:
                    results.append(
                        NormalizedResult(
                            title=title,
                            url=url,
                            snippet=snippet,
                            provider=self.name,
                            timestamp=now_str
                        )
                    )

        return results

    @staticmethod
    def _clean_url(url: str) -> str:
        """Extract target URL if wrapped in DDG redirect format (uddg=...)."""
        if "uddg=" in url:
            try:
                url = url.split("uddg=")[1].split("&")[0]
                url = urllib.parse.unquote(url)
            except Exception:
                pass
        return url.strip()
