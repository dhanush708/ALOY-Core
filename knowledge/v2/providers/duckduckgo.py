"""
ALOY Search V2 — DuckDuckGo Provider

Production implementation of ISearchProvider using DuckDuckGo HTML interface.
Features browser-like User-Agent rotation, HTTP error detection (403, 429), CAPTCHA
and anti-bot challenge detection, HTML structure validation, and explicit error classification.
"""

import asyncio
import logging
import random
import re
import urllib.parse
import urllib.request
import urllib.error
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from knowledge.v2.interfaces import ISearchProvider
from knowledge.v2.models import NormalizedResult

logger = logging.getLogger(__name__)


# ── Explicit Error Classification & Outcomes ──────────────────────────────────

class ProviderOutcome:
    SUCCESS = "SUCCESS"
    NO_RESULTS = "NO_RESULTS"
    CAPTCHA = "CAPTCHA"
    RATE_LIMITED = "RATE_LIMITED"
    HTTP_403 = "HTTP_403"
    NETWORK_ERROR = "NETWORK_ERROR"
    TIMEOUT = "TIMEOUT"
    PARSER_FAILURE = "PARSER_FAILURE"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"


class ProviderExecutionError(Exception):
    """Base exception for DuckDuckGo provider execution failures."""
    def __init__(self, message: str, outcome: str):
        super().__init__(message)
        self.outcome = outcome


class ProviderCaptchaError(ProviderExecutionError):
    def __init__(self, message: str = "CAPTCHA challenge detected"):
        super().__init__(message, outcome=ProviderOutcome.CAPTCHA)


class ProviderRateLimitError(ProviderExecutionError):
    def __init__(self, message: str = "Rate limit HTTP 429"):
        super().__init__(message, outcome=ProviderOutcome.RATE_LIMITED)


class ProviderForbiddenError(ProviderExecutionError):
    def __init__(self, message: str = "HTTP 403 Forbidden"):
        super().__init__(message, outcome=ProviderOutcome.HTTP_403)


class ProviderNetworkError(ProviderExecutionError):
    def __init__(self, message: str):
        super().__init__(message, outcome=ProviderOutcome.NETWORK_ERROR)


class ProviderParserError(ProviderExecutionError):
    def __init__(self, message: str):
        super().__init__(message, outcome=ProviderOutcome.PARSER_FAILURE)


# ── Regex Parsers & User-Agents ───────────────────────────────────────────────

_USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
]

# Primary DDG Result Pattern
_PRIMARY_PATTERN = re.compile(
    r'<div class="[^"]*web-result[^"]*">.*?'
    r'<a[^>]*class="result__a"[^>]*href="(?P<url>[^"]*)"[^>]*>(?P<title>.*?)</a>.*?'
    r'<a[^>]*class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
    re.DOTALL
)

# Secondary Fallback Patterns
_SNIPPET_PATTERN = re.compile(r'<a[^>]*class="result__snippet[^"]*"[^>]*>(.*?)</a>', re.DOTALL)
_URL_PATTERN = re.compile(r'<a[^>]*class="result__url"[^>]*href="(?P<url>[^"]*)"[^>]*>(.*?)</a>', re.DOTALL)
_TITLE_PATTERN = re.compile(r'<a[^>]*class="result__a"[^>]*>(.*?)</a>', re.DOTALL)


class DuckDuckGoProvider(ISearchProvider):
    """Robust DuckDuckGo web search provider using HTML scraping."""

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
        """Execute a DuckDuckGo web search query with robust error handling and classification."""
        if not query or not query.strip():
            return []

        options = options or {}
        max_results = options.get("max_results", 6)

        query_encoded = urllib.parse.quote_plus(query.strip())
        url = f"https://html.duckduckgo.com/html/?q={query_encoded}"

        loop = asyncio.get_running_loop()

        def _fetch() -> str:
            headers = {
                'User-Agent': random.choice(_USER_AGENTS),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'DNT': '1',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
            }
            req = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=5) as response:
                    return response.read().decode('utf-8', errors='replace')
            except urllib.error.HTTPError as e:
                if e.code == 403:
                    logger.warning(f"DuckDuckGo request failed -> HTTP 403 Forbidden for query '{query}'")
                    raise ProviderForbiddenError(f"HTTP 403 Forbidden for query '{query}'")
                elif e.code == 429:
                    logger.warning(f"DuckDuckGo request failed -> HTTP 429 Rate Limited for query '{query}'")
                    raise ProviderRateLimitError(f"HTTP 429 Rate Limited for query '{query}'")
                else:
                    logger.warning(f"DuckDuckGo request failed -> HTTP {e.code} for query '{query}'")
                    raise ProviderNetworkError(f"HTTP Error {e.code} for query '{query}'")
            except urllib.error.URLError as e:
                logger.warning(f"DuckDuckGo request failed -> Network error: {e.reason}")
                raise ProviderNetworkError(f"Network error: {e.reason}")
            except Exception as e:
                logger.warning(f"DuckDuckGo request failed -> Exception: {e}")
                raise ProviderNetworkError(f"Network error: {e}")

        try:
            logger.info(f"DuckDuckGo request started for query '{query}'")
            html = await asyncio.wait_for(
                loop.run_in_executor(None, _fetch),
                timeout=self._timeout
            )
            results = self._parse_html(html, max_results=max_results)
            if results:
                logger.info(f"DuckDuckGo search succeeded -> {len(results)} results retrieved")
            else:
                logger.info(f"DuckDuckGo search succeeded -> NO_RESULTS for query '{query}'")
            return results

        except asyncio.TimeoutError:
            logger.warning(f"DuckDuckGo search request failed -> TIMEOUT after {self._timeout}s for query '{query}'")
            raise ProviderExecutionError(f"Timeout after {self._timeout}s", outcome=ProviderOutcome.TIMEOUT)
        except ProviderExecutionError:
            raise
        except Exception as e:
            logger.error(f"DuckDuckGo search request failed -> Unexpected error: {e}")
            raise ProviderExecutionError(str(e), outcome=ProviderOutcome.PROVIDER_FAILURE)

    def _parse_html(self, html: str, max_results: int = 6) -> List[NormalizedResult]:
        """Parse raw DuckDuckGo HTML with CAPTCHA detection and HTML structure validation."""
        if not html or not html.strip():
            raise ProviderParserError("Empty HTML response received")

        html_lower = html.lower()

        # 1. CAPTCHA / Anti-Bot Challenge Detection
        if any(pattern in html_lower for pattern in ["captcha", "ddg-captcha", "anomaly_detected", "check if you're a human", "challenge-form"]):
            logger.warning("DuckDuckGo request failed -> CAPTCHA detected")
            raise ProviderCaptchaError("DuckDuckGo returned a CAPTCHA challenge page")

        # 2. Extract results via Primary Pattern
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
            return results

        # 3. Fallback secondary extraction
        t_matches = _TITLE_PATTERN.findall(html)
        u_matches = _URL_PATTERN.findall(html)
        s_matches = _SNIPPET_PATTERN.findall(html)

        if t_matches and u_matches:
            count = min(len(t_matches), len(u_matches), len(s_matches), max_results)
            for i in range(count):
                title = re.sub(r'<[^>]+>', '', t_matches[i]).strip()
                raw_url_val = u_matches[i][0] if isinstance(u_matches[i], tuple) else u_matches[i]
                url = self._clean_url(raw_url_val.strip())
                snippet_val = s_matches[i][0] if i < len(s_matches) else ""
                if isinstance(snippet_val, tuple):
                    snippet_val = snippet_val[0]
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
            if results:
                return results

        # 4. Check for genuine NO_RESULTS vs HTML structure failure
        if any(term in html_lower for term in ["no results", "no matching", "not found", "did not match any documents"]):
            return []

        # 5. Missing expected DDG containers -> Structural Parser Failure
        logger.warning("DuckDuckGo request failed -> PARSER_FAILURE (expected result containers missing)")
        raise ProviderParserError("Failed to parse DDG results: expected containers missing in HTML response")

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
