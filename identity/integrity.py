import re
import logging
from typing import AsyncGenerator, Optional

logger = logging.getLogger(__name__)

class PromptIntegrityFilter:
    """Detects and strips accidental system prompt, reasoning, or XML leakage from assistant outputs."""

    LEAKAGE_XML_PATTERNS = [
        re.compile(r"<identity>.*?</identity>", re.DOTALL | re.IGNORECASE),
        re.compile(r"<history>.*?</history>", re.DOTALL | re.IGNORECASE),
        re.compile(r"<context>.*?</context>", re.DOTALL | re.IGNORECASE),
        re.compile(r"<memory>.*?</memory>", re.DOTALL | re.IGNORECASE),
        re.compile(r"<memories>.*?</memories>", re.DOTALL | re.IGNORECASE),
        re.compile(r"<prompt>.*?</prompt>", re.DOTALL | re.IGNORECASE),
        re.compile(r"<system>.*?</system>", re.DOTALL | re.IGNORECASE),
        re.compile(r"<tools>.*?</tools>", re.DOTALL | re.IGNORECASE),
        re.compile(r"<project>.*?</project>", re.DOTALL | re.IGNORECASE),
        re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE),
    ]

    UNCLOSED_TAG_PATTERN = re.compile(
        r"<(identity|history|context|memory|memories|prompt|system|tools|project|think)\b[^>]*>",
        re.IGNORECASE
    )

    LEAKAGE_HEADERS = [
        re.compile(r"^\s*(System|User):\s*.*$", re.IGNORECASE | re.MULTILINE),
        re.compile(r"^\s*Assistant:\s*", re.IGNORECASE | re.MULTILINE),
    ]

    def __init__(self):
        # Keeps track of sliding window buffer for streaming clean up
        self.buffer = ""

    def clean_text(self, text: str) -> str:
        """Applies prompt integrity cleaning to complete text."""
        cleaned = text

        # 1. Clean XML blocks
        for pattern in self.LEAKAGE_XML_PATTERNS:
            cleaned = pattern.sub("", cleaned)

        # 2. Check for any unclosed opening tags
        # Blocked tags: identity, history, context, memory, memories, prompt, system, tools, project, think
        tags = ["identity", "history", "context", "memory", "memories", "prompt", "system", "tools", "project", "think"]
        for tag in tags:
            open_tag = f"<{tag}"
            close_tag = f"</{tag}>"
            if open_tag in cleaned.lower() and close_tag not in cleaned.lower():
                idx = cleaned.lower().find(open_tag)
                cleaned = cleaned[:idx]

        # 3. Clean remaining unclosed or dangling opening tags
        cleaned = self.UNCLOSED_TAG_PATTERN.sub("", cleaned)

        # 4. Clean headers (e.g. "Assistant:")
        for header in self.LEAKAGE_HEADERS:
            cleaned = header.sub("", cleaned)

        return cleaned

    def find_first_unclosed_tag_index(self, text: str) -> Optional[int]:
        """Finds the index of the first opening tag that lacks a corresponding closing tag."""
        tags = ["identity", "history", "context", "memory", "memories", "prompt", "system", "tools", "project", "think"]
        first_idx = None
        for tag in tags:
            open_tag = f"<{tag}"
            close_tag = f"</{tag}>"
            
            start_pos = 0
            while True:
                idx = text.lower().find(open_tag, start_pos)
                if idx == -1:
                    break
                
                # Check if there is a matching close_tag after this open_tag
                if close_tag not in text.lower()[idx:]:
                    if first_idx is None or idx < first_idx:
                        first_idx = idx
                    break
                else:
                    start_pos = idx + len(open_tag)
                    
        return first_idx

    async def stream_filter(self, token_generator: AsyncGenerator[str, None]) -> AsyncGenerator[str, None]:
        """Asynchronously cleans and yields tokens while filtering out leaky structures."""
        async for chunk in token_generator:
            self.buffer += chunk

            # Check if there's a trailing partial tag or header prefix to hold back
            keep_len = 0
            potential_start = False
            tags = ["identity", "history", "context", "memory", "memories", "prompt", "system", "tools", "project", "think"]
            
            # Check prefixes of open tags (<tag) and close tags (</tag>)
            for tag in tags:
                open_start = f"<{tag}"
                for i in range(1, len(open_start) + 1):
                    if open_start.startswith(self.buffer[-i:]):
                        potential_start = True
                        keep_len = max(keep_len, i)
                        break
                
                close_start = f"</{tag}>"
                for i in range(1, len(close_start) + 1):
                    if close_start.startswith(self.buffer[-i:]):
                        potential_start = True
                        keep_len = max(keep_len, i)
                        break

            # Check header prefixes
            for prefix in ["System:", "Assistant:", "User:"]:
                for i in range(1, len(prefix) + 1):
                    if prefix.startswith(self.buffer[-i:]):
                        potential_start = True
                        keep_len = max(keep_len, i)
                        break

            # Divide buffer into stable and trailing parts
            if keep_len > 0:
                safe_buffer = self.buffer[:-keep_len]
            else:
                safe_buffer = self.buffer

            # Find first unclosed tag in the stable part
            unclosed_idx = self.find_first_unclosed_tag_index(safe_buffer)
            
            if unclosed_idx is not None:
                # Safe to yield everything before the unclosed tag (after cleaning)
                yield_part = safe_buffer[:unclosed_idx]
                cleaned_yield = self.clean_text(yield_part)
                if cleaned_yield:
                    yield cleaned_yield
                # Keep everything from the unclosed tag onwards in the buffer
                self.buffer = self.buffer[unclosed_idx:]
            else:
                # No unclosed tag in stable part, safe to yield the cleaned stable part
                cleaned_yield = self.clean_text(safe_buffer)
                if cleaned_yield:
                    yield cleaned_yield
                # Keep only the trailing held back part in the buffer
                if keep_len > 0:
                    self.buffer = self.buffer[-keep_len:]
                else:
                    self.buffer = ""

        # Flush any remaining buffer at the end of stream
        if self.buffer:
            final_cleaned = self.clean_text(self.buffer)
            if final_cleaned:
                yield final_cleaned
            self.buffer = ""
