import os
import re
import logging
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class OfflineDocIndexer:
    """Chunks and indexes offline documentation files into the Memory system."""

    def __init__(self, memory_manager):
        self.memory_manager = memory_manager

    async def index_directory(
        self,
        dir_path: str | Path,
        package: str,
        version: str,
        doc_type: str = "api_reference"
    ) -> int:
        """Indexes all text/markdown files in a directory."""
        path = Path(dir_path)
        if not path.exists() or not path.is_dir():
            logger.warning(f"Documentation directory does not exist: {dir_path}")
            return 0

        package = package.strip().lower()
        version = version.strip().lower()
        doc_type = doc_type.strip().lower()

        count = 0
        for file_path in path.rglob("*"):
            if file_path.is_dir() or file_path.suffix not in [".md", ".txt", ".html", ".htm"]:
                continue

            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                if file_path.suffix in [".html", ".htm"]:
                    content = self._clean_html(content)

                chunks = self._chunk_text(content, file_path.name)

                for idx, chunk in enumerate(chunks):
                    metadata = {
                        "package": package,
                        "version": version,
                        "file_name": file_path.name,
                        "chunk_index": idx,
                        "doc_type": doc_type
                    }
                    tags = [
                        "doc:offline",
                        f"package:{package}",
                        f"version:{version}",
                        f"doc_type:{doc_type}"
                    ]
                    
                    mem = await self.memory_manager.store(
                        type="documentation",
                        content=chunk,
                        tier="permanent",
                        importance=0.9,
                        is_protected=True,
                        category="documentation",
                        source=f"offline_doc_{package}",
                        source_id=f"{file_path.name}_chunk_{idx}",
                        metadata=metadata
                    )
                    self.memory_manager.tags.add_tags(mem.id, tags)
                    count += 1
            except Exception as e:
                logger.error(f"Failed to index documentation file {file_path}: {e}")

        return count

    def _clean_html(self, html: str) -> str:
        """Basic HTML text extraction by stripping tags."""
        text = re.sub(r'<(script|style)\b[^>]*>([\s\S]*?)<\/\1>', '', html, flags=re.I)
        text = re.sub(r'<br\s*\/?>', '\n', text, flags=re.I)
        text = re.sub(r'<\/?(p|div|h1|h2|h3|h4|h5|h6|li|tr)\b[^>]*>', '\n', text, flags=re.I)
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n\s*\n+', '\n\n', text)
        return text.strip()

    def _chunk_text(self, text: str, file_name: str) -> List[str]:
        """Chunks text by Markdown headings or character window limits."""
        chunks = []
        header_splits = re.split(r'\n(#{1,6}\s+.*)\n', text)
        
        if len(header_splits) > 1:
            current_chunk = header_splits[0].strip()
            for i in range(1, len(header_splits), 2):
                header = header_splits[i].strip()
                body = header_splits[i+1].strip() if i+1 < len(header_splits) else ""
                combined = f"{header}\n{body}"
                if len(current_chunk) + len(combined) < 1500:
                    current_chunk += "\n\n" + combined
                else:
                    if current_chunk:
                        chunks.append(current_chunk)
                    current_chunk = combined
            if current_chunk:
                chunks.append(current_chunk)
        else:
            paragraphs = text.split("\n\n")
            current_chunk = ""
            for p in paragraphs:
                p = p.strip()
                if not p:
                    continue
                if len(current_chunk) + len(p) < 1500:
                    current_chunk += "\n\n" + p if current_chunk else p
                else:
                    if current_chunk:
                        chunks.append(current_chunk)
                    current_chunk = p
            if current_chunk:
                chunks.append(current_chunk)

        final_chunks = []
        for chunk in chunks:
            if len(chunk) > 3000:
                sub_chunks = self._split_large_text(chunk, max_size=2000)
                final_chunks.extend(sub_chunks)
            else:
                final_chunks.append(chunk)

        return [f"[File: {file_name}]\n{c.strip()}" for c in final_chunks if c.strip()]

    def _split_large_text(self, text: str, max_size: int = 2000) -> List[str]:
        """Slices massive chunks into smaller pieces by character length."""
        segments = []
        start = 0
        while start < len(text):
            end = start + max_size
            if end >= len(text):
                segments.append(text[start:])
                break
            split_idx = text.rfind("\n", start, end)
            if split_idx == -1 or split_idx <= start:
                split_idx = text.rfind(" ", start, end)
            if split_idx == -1 or split_idx <= start:
                split_idx = end
            segments.append(text[start:split_idx])
            start = split_idx
        return segments
