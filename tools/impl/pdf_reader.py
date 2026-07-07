import os
import re
import logging
from typing import Dict, Any
from tools.base import BaseTool, ToolMetadata

logger = logging.getLogger(__name__)

class PDFReaderTool(BaseTool):
    """Tool for reading text from PDF files, with fallback to pure-Python parsing."""
    
    def __init__(self):
        metadata = ToolMetadata(
            name="pdf_reader",
            description="Extract and read the text content of a PDF file.",
            category=["Documents"],
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the PDF file relative to the workspace root."
                    }
                },
                "required": ["path"]
            },
            permissions_required=["read_file"],
            timeout_seconds=20
        )
        super().__init__(metadata)
        
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> str:
        path = params["path"]
        
        if not os.path.exists(path):
            raise FileNotFoundError(f"PDF file not found: {path}")
            
        try:
            import pypdf
            logger.info("Using pypdf for PDF text extraction.")
            reader = pypdf.PdfReader(path)
            text_pages = []
            for i, page in enumerate(reader.pages):
                page_text = page.extract_text()
                if page_text:
                    text_pages.append(f"--- Page {i+1} ---\n{page_text}")
            return "\n\n".join(text_pages)
        except ImportError:
            logger.warning("pypdf not found. Falling back to pure Python PDF stream extraction.")
            return self._extract_text_pure_python(path)
            
    def _extract_text_pure_python(self, path: str) -> str:
        """Pure-Python fallback to extract printable strings from PDF streams."""
        try:
            with open(path, "rb") as f:
                content = f.read()
                
            # Find BT...ET text blocks in PDF binary data
            text_chunks = []
            for match in re.finditer(b"BT(.*?)ET", content, re.DOTALL):
                block = match.group(1)
                # Find content inside parentheses (e.g., (hello) Tj)
                strings = re.findall(br"\((.*?)\)", block)
                for s in strings:
                    try:
                        decoded = s.decode("utf-8", errors="ignore")
                        # Basic PDF text escaping
                        decoded = decoded.replace(r"\)", ")").replace(r"\(", "(")
                        if len(decoded.strip()) > 0:
                            text_chunks.append(decoded)
                    except Exception:
                        pass
                        
            if not text_chunks:
                # If no text blocks found, extract printable ASCII chunks as fallback
                text_runs = re.findall(r"[a-zA-Z0-9\s\.,;:!?@#%&*()_+\-=\[\]{}|\'\"<>]{6,}", content.decode("latin1", errors="ignore"))
                # Filter out obvious PDF keywords
                filtered = [run for run in text_runs if not any(kw in run for kw in ("obj", "endobj", "stream", "endstream", "xref", "trailer"))]
                return f"[Fallback Extractor Output]\n" + " ".join(filtered[:500])
                
            return f"[Fallback Extractor Output]\n" + " ".join(text_chunks)
        except Exception as e:
            return f"Error reading PDF file via fallback: {e}"
