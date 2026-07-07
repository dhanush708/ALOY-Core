import urllib.request
import urllib.parse
import asyncio
import logging
import re
from typing import Dict, Any
from tools.base import BaseTool, ToolMetadata

logger = logging.getLogger(__name__)

class BrowserTool(BaseTool):
    """Tool for reading web page content by fetching and cleaning HTML."""
    
    def __init__(self):
        metadata = ToolMetadata(
            name="browser",
            description="Access and read web page content from a URL.",
            category=["Internet"],
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL of the webpage to fetch."
                    }
                },
                "required": ["url"]
            },
            permissions_required=["read_url"],
            timeout_seconds=20,
            supports_streaming=True,
            supports_cancellation=True
        )
        super().__init__(metadata)
        
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> str:
        url = params["url"]
        
        # Parse URL to validate scheme
        parsed_url = urllib.parse.urlparse(url)
        if parsed_url.scheme not in ("http", "https"):
            raise ValueError(f"Invalid URL scheme: {parsed_url.scheme}. Only http and https are allowed.")
            
        logger.info(f"Fetching URL: {url}")
        
        # Perform async request using loop.run_in_executor to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        
        def fetch():
            req = urllib.request.Request(
                url, 
                headers={'User-Agent': 'Mozilla/5.0 (ALOY AI Bot)'}
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                return response.read().decode('utf-8', errors='replace')
                
        try:
            html = await asyncio.wait_for(
                loop.run_in_executor(None, fetch), 
                timeout=18.0
            )
            # Basic HTML to text conversion
            text = self._clean_html(html)
            return text
        except asyncio.TimeoutError:
            raise TimeoutError(f"Request to {url} timed out.")
            
    def _clean_html(self, html: str) -> str:
        """Strip HTML tags, scripts, and styles to get clean text content."""
        # Remove script and style elements
        html = re.sub(r'<(script|style|noscript)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
        # Remove HTML comments
        html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
        # Replace tags with newlines/whitespace
        html = re.sub(r'<[^>]+>', ' ', html)
        # Standardize spacing
        lines = (line.strip() for line in html.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)
        return text
