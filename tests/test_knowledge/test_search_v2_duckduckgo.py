"""
Unit tests for ALOY Search V2 DuckDuckGo Provider (knowledge/v2/providers/duckduckgo.py).
Network calls are 100% mocked to guarantee zero internet dependency.
Includes complete error classification test coverage.
"""

import asyncio
import urllib.error
import pytest
from unittest.mock import patch, MagicMock

from knowledge.v2.providers.duckduckgo import (
    DuckDuckGoProvider,
    ProviderOutcome,
    ProviderExecutionError,
    ProviderCaptchaError,
    ProviderRateLimitError,
    ProviderForbiddenError,
    ProviderNetworkError,
    ProviderParserError,
)
from knowledge.v2.models import NormalizedResult
from knowledge.v2.interfaces import ISearchProvider

# Sample DDG HTML outputs for testing
SAMPLE_DDG_PRIMARY_HTML = """
<html>
<body>
<div class="result results_links results_links_deep web-result ">
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.python.org%2F">Python Source Code</a>
    <a class="result__snippet" href="#">Official homepage for Python programming language.</a>
</div>
<div class="result results_links results_links_deep web-result ">
    <a class="result__a" href="https://github.com/python/cpython">GitHub - python/cpython</a>
    <a class="result__snippet" href="#">The Python programming language implementation.</a>
</div>
</body>
</html>
"""

SAMPLE_DDG_NO_RESULTS_HTML = """
<html>
<body>
<div id="links_wrapper">
    <div class="no-results">No results found for xyz123nonexistent.</div>
</div>
</body>
</html>
"""

SAMPLE_DDG_CAPTCHA_HTML = """
<html>
<body>
<div class="ddg-captcha">
    <h2>Please complete the CAPTCHA challenge below</h2>
</div>
</body>
</html>
"""


class TestDuckDuckGoProvider:

    def test_provider_interface_compliance(self):
        provider = DuckDuckGoProvider()
        assert isinstance(provider, ISearchProvider)
        assert provider.name == "duckduckgo"
        assert provider.capabilities == ["web", "search"]

    @pytest.mark.asyncio
    async def test_is_available(self):
        provider = DuckDuckGoProvider()
        assert await provider.is_available() is True

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty_list(self):
        provider = DuckDuckGoProvider()
        res1 = await provider.execute("")
        res2 = await provider.execute("   ")
        assert res1 == []
        assert res2 == []

    @pytest.mark.asyncio
    async def test_successful_search_primary_parser(self):
        provider = DuckDuckGoProvider()

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = SAMPLE_DDG_PRIMARY_HTML.encode('utf-8')
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            results = await provider.execute("python programming")
            assert len(results) == 2
            assert results[0].title == "Python Source Code"
            assert results[0].url == "https://www.python.org/"
            assert results[0].provider == "duckduckgo"

    def test_genuine_no_results_handling(self):
        provider = DuckDuckGoProvider()
        results = provider._parse_html(SAMPLE_DDG_NO_RESULTS_HTML)
        assert results == []

    @pytest.mark.asyncio
    async def test_captcha_detection_raises_captcha_error(self):
        provider = DuckDuckGoProvider()
        with pytest.raises(ProviderCaptchaError) as exc_info:
            provider._parse_html(SAMPLE_DDG_CAPTCHA_HTML)
        assert exc_info.value.outcome == ProviderOutcome.CAPTCHA

    @pytest.mark.asyncio
    async def test_http_403_raises_forbidden_error(self):
        provider = DuckDuckGoProvider()
        http_err = urllib.error.HTTPError("url", 403, "Forbidden", {}, None)

        with patch("urllib.request.urlopen", side_effect=http_err):
            with pytest.raises(ProviderForbiddenError) as exc_info:
                await provider.execute("test 403")
            assert exc_info.value.outcome == ProviderOutcome.HTTP_403

    @pytest.mark.asyncio
    async def test_http_429_raises_rate_limit_error(self):
        provider = DuckDuckGoProvider()
        http_err = urllib.error.HTTPError("url", 429, "Too Many Requests", {}, None)

        with patch("urllib.request.urlopen", side_effect=http_err):
            with pytest.raises(ProviderRateLimitError) as exc_info:
                await provider.execute("test 429")
            assert exc_info.value.outcome == ProviderOutcome.RATE_LIMITED

    @pytest.mark.asyncio
    async def test_malformed_html_raises_parser_error(self):
        provider = DuckDuckGoProvider()
        malformed_html = "<html><body><div>Unexpected unstructured body</div></body></html>"

        with pytest.raises(ProviderParserError) as exc_info:
            provider._parse_html(malformed_html)
        assert exc_info.value.outcome == ProviderOutcome.PARSER_FAILURE

    @pytest.mark.asyncio
    async def test_search_timeout_handling(self):
        provider = DuckDuckGoProvider(timeout_seconds=0.1)

        def slow_fetch(*args, **kwargs):
            import time
            time.sleep(0.5)
            return "<html></html>"

        with patch("urllib.request.urlopen", side_effect=slow_fetch):
            with pytest.raises(ProviderExecutionError) as exc_info:
                await provider.execute("timeout test")
            assert exc_info.value.outcome == ProviderOutcome.TIMEOUT

    @pytest.mark.asyncio
    async def test_network_exception_handling(self):
        provider = DuckDuckGoProvider()

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
            with pytest.raises(ProviderNetworkError) as exc_info:
                await provider.execute("error test")
            assert exc_info.value.outcome == ProviderOutcome.NETWORK_ERROR

    def test_clean_url_uddg_redirect(self):
        raw_uddg = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python.org%2F3%2F&rut=123"
        cleaned = DuckDuckGoProvider._clean_url(raw_uddg)
        assert cleaned == "https://docs.python.org/3/"
