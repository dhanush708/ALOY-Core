"""
Unit tests for ALOY Search V2 DuckDuckGo Provider (knowledge/v2/providers/duckduckgo.py).
Network calls are 100% mocked to guarantee zero internet dependency.
"""

import asyncio
import pytest
from unittest.mock import patch, MagicMock
from knowledge.v2.providers.duckduckgo import DuckDuckGoProvider
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

SAMPLE_DDG_FALLBACK_HTML = """
<html>
<body>
<div class="other-format">
    <a class="result__a" href="#">Fallback Title 1</a>
    <a class="result__url" href="https://fallback1.org">fallback1.org</a>
    <a class="result__snippet">Fallback Snippet 1</a>
</div>
<div class="other-format">
    <a class="result__a" href="#">Fallback Title 2</a>
    <a class="result__url" href="https://fallback2.org">fallback2.org</a>
    <a class="result__snippet">Fallback Snippet 2</a>
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

        with patch.object(provider, '_parse_html') as mock_parse:
            mock_parse.return_value = [
                NormalizedResult(
                    title="Python Source Code",
                    url="https://www.python.org/",
                    snippet="Official homepage",
                    provider="duckduckgo"
                )
            ]
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_resp = MagicMock()
                mock_resp.read.return_value = SAMPLE_DDG_PRIMARY_HTML.encode('utf-8')
                mock_urlopen.return_value.__enter__.return_value = mock_resp

                results = await provider.execute("python programming")
                assert len(results) == 1
                assert results[0].title == "Python Source Code"
                assert results[0].url == "https://www.python.org/"
                assert results[0].provider == "duckduckgo"

    def test_parse_primary_html(self):
        provider = DuckDuckGoProvider()
        results = provider._parse_html(SAMPLE_DDG_PRIMARY_HTML, max_results=5)

        assert len(results) == 2
        assert results[0].title == "Python Source Code"
        assert results[0].url == "https://www.python.org/"
        assert results[0].snippet == "Official homepage for Python programming language."
        assert results[1].title == "GitHub - python/cpython"
        assert results[1].url == "https://github.com/python/cpython"

    def test_parse_fallback_html(self):
        provider = DuckDuckGoProvider()
        results = provider._parse_html(SAMPLE_DDG_FALLBACK_HTML, max_results=5)

        assert len(results) == 2
        assert results[0].title == "Fallback Title 1"
        assert results[0].url == "https://fallback1.org"
        assert results[0].snippet == "Fallback Snippet 1"

    def test_clean_url_uddg_redirect(self):
        raw_uddg = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python.org%2F3%2F&rut=123"
        cleaned = DuckDuckGoProvider._clean_url(raw_uddg)
        assert cleaned == "https://docs.python.org/3/"

        standard_url = "https://example.com/test"
        assert DuckDuckGoProvider._clean_url(standard_url) == standard_url

    @pytest.mark.asyncio
    async def test_search_timeout_handling(self):
        provider = DuckDuckGoProvider(timeout_seconds=0.1)

        def slow_fetch():
            import time
            time.sleep(0.5)
            return "<html></html>"

        with patch("urllib.request.urlopen", side_effect=slow_fetch):
            results = await provider.execute("timeout test")
            assert results == []

    @pytest.mark.asyncio
    async def test_network_exception_handling(self):
        provider = DuckDuckGoProvider()

        with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
            results = await provider.execute("error test")
            assert results == []

    def test_max_results_option(self):
        provider = DuckDuckGoProvider()
        results = provider._parse_html(SAMPLE_DDG_PRIMARY_HTML, max_results=1)
        assert len(results) == 1
        assert results[0].title == "Python Source Code"
