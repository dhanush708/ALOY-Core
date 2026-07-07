import urllib.request
import urllib.parse
import asyncio
import logging
import re
from typing import Dict, Any
from tools.base import BaseTool, ToolMetadata

logger = logging.getLogger(__name__)

class WebSearchTool(BaseTool):
    """Tool for performing web searches using DuckDuckGo's HTML interface."""
    
    def __init__(self):
        metadata = ToolMetadata(
            name="web_search",
            description="Search the internet for info on a query.",
            category=["Internet", "Knowledge"],
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query."
                    }
                },
                "required": ["query"]
            },
            permissions_required=["read_url"],
            timeout_seconds=20
        )
        super().__init__(metadata)
        
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> str:
        query = params["query"]
        query_encoded = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={query_encoded}"
        
        loop = asyncio.get_running_loop()
        
        def fetch_results():
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
                loop.run_in_executor(None, fetch_results), 
                timeout=7.0
            )
            # Parse DDG HTML results
            results = self._parse_ddg_html(html)
            if not results:
                return f"No results found for query: '{query}'."
            return results
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return f"Failed to perform search: {str(e)}. Please check your network connection."
            
    def _parse_ddg_html(self, html: str) -> str:
        """Extract title, link, and snippet from DuckDuckGo HTML response."""
        # Clean up results
        results = []
        
        # A result entry looks like:
        # <div class="result results_links results_links_deep web-result ">
        # ... <a class="result__a" href="[url]">[title]</a>
        # ... <a class="result__snippet" ...>[snippet]</a>
        pattern = re.compile(
            r'<div class="[^"]*web-result[^"]*">.*?'
            r'<a[^>]*class="result__a"[^>]*href="(?P<url>[^"]*)"[^>]*>(?P<title>.*?)</a>.*?'
            r'<a[^>]*class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
            re.DOTALL
        )
        
        matches = list(pattern.finditer(html))
        
        # If pattern didn't match (DDG changes HTML frequently), do a fallback search
        if not matches:
            # Fallback regex parsing
            snippet_pattern = re.compile(r'<a[^>]*class="result__snippet[^"]*"[^>]*>(.*?)</a>', re.DOTALL)
            url_pattern = re.compile(r'<a[^>]*class="result__url"[^>]*href="(?P<url>[^"]*)"[^>]*>(.*?)</a>', re.DOTALL)
            title_pattern = re.compile(r'<a[^>]*class="result__a"[^>]*>(.*?)</a>', re.DOTALL)
            
            t_matches = title_pattern.findall(html)
            u_matches = url_pattern.findall(html)
            s_matches = snippet_pattern.findall(html)
            
            for i in range(min(len(t_matches), len(u_matches), len(s_matches))):
                title = re.sub(r'<[^>]+>', '', t_matches[i]).strip()
                url = urllib.parse.unquote(u_matches[i].strip())
                snippet = re.sub(r'<[^>]+>', '', s_matches[i]).strip()
                results.append(f"Title: {title}\nURL: {url}\nSnippet: {snippet}\n---")
        else:
            for m in matches[:6]:  # Limit to top 6 results
                title = re.sub(r'<[^>]+>', '', m.group("title")).strip()
                url = m.group("url")
                # Parse DDG redirection URL if applicable
                if "uddg=" in url:
                    url = url.split("uddg=")[1].split("&")[0]
                    url = urllib.parse.unquote(url)
                snippet = re.sub(r'<[^>]+>', '', m.group("snippet")).strip()
                results.append(f"Title: {title}\nURL: {url}\nSnippet: {snippet}\n---")
                
        return "\n".join(results)

