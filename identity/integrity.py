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
        r"</?(identity|history|context|memory|memories|prompt|system|tools|project|think)\b[^>]*>",
        re.IGNORECASE
    )

    LEAKAGE_HEADERS = [
        # Role prefixes from raw completion format
        re.compile(r"^\s*(System|User):\s*.*$", re.IGNORECASE | re.MULTILINE),
        re.compile(r"^\s*Assistant:\s*", re.IGNORECASE | re.MULTILINE),
        re.compile(r"^\s*ALOY:\s*", re.IGNORECASE | re.MULTILINE),
        # Identity engine section headers
        re.compile(r"^\s*Personal Info:\s*", re.IGNORECASE | re.MULTILINE),
        re.compile(r"^\s*Rules:\s*", re.IGNORECASE | re.MULTILINE),
        re.compile(r"^\s*Context:\s*", re.IGNORECASE | re.MULTILINE),
        re.compile(r"^\s*Knowledge Router:\s*.*$", re.IGNORECASE | re.MULTILINE),
        re.compile(r"^\s*Documentation Intelligence Tool:\s*.*$", re.IGNORECASE | re.MULTILINE),
        # Full-line prompt section banners from identity prompt
        re.compile(r"^ABSOLUTE RULES.*$", re.IGNORECASE | re.MULTILINE),
        re.compile(r"^CURRENT SYSTEM CAPABILITIES.*$", re.IGNORECASE | re.MULTILINE),
        re.compile(r"^CURRENT WORKSPACE.*$", re.IGNORECASE | re.MULTILINE),
        re.compile(r"^PERSONALITY STYLES.*$", re.IGNORECASE | re.MULTILINE),
        re.compile(r"^Previous conversations:.*$", re.IGNORECASE | re.MULTILINE),
    ]

    # Patterns that indicate a response has leaked prompt content at its start
    _RESPONSE_START_LEAK_RE = re.compile(
        r"^\s*(System:|Rules:|Context:|Personal Info:|Knowledge Router:|Documentation Intelligence Tool:|ALOY:|Assistant:|ABSOLUTE RULES|CURRENT SYSTEM CAPABILITIES|PERSONALITY STYLES|Previous conversations:)",
        re.IGNORECASE
    )

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

        # 4. Clean headers (e.g. "Assistant:", section banners)
        for header in self.LEAKAGE_HEADERS:
            cleaned = header.sub("", cleaned)

        return cleaned

    def sanitize_response_start(self, text: str) -> str:
        """Strips leaked prompt-header prefixes from the very start of a complete response.

        This is the last-resort guard: if the model echoed a prompt-section header
        as the first line of its response, remove it and trim leading whitespace.
        """
        lines = text.split("\n")
        # Drop leading lines that match known prompt leak patterns
        while lines and self._RESPONSE_START_LEAK_RE.match(lines[0]):
            lines.pop(0)
        cleaned = "\n".join(lines).lstrip()
        # Apply full clean_text as well
        return self.clean_text(cleaned)

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

    def process_chunk(self, chunk: str) -> str:
        """Statefully processes a chunk of text, buffering partial tags and headers.
        Returns the safe, cleaned text that can be emitted immediately."""
        self.buffer += chunk

        keep_len = 0
        tags = ["identity", "history", "context", "memory", "memories", "prompt", "system", "tools", "project", "think"]
        
        # Check prefixes of open tags (<tag) and close tags (</tag>)
        for tag in tags:
            open_start = f"<{tag}"
            for i in range(1, len(open_start) + 1):
                if open_start.startswith(self.buffer[-i:].lower()):
                    keep_len = max(keep_len, i)
                    break
            
            close_start = f"</{tag}>"
            for i in range(1, len(close_start) + 1):
                if close_start.startswith(self.buffer[-i:].lower()):
                    keep_len = max(keep_len, i)
                    break

        # Check header prefixes
        for prefix in ["System:", "Assistant:", "User:"]:
            for i in range(1, len(prefix) + 1):
                if prefix.lower().startswith(self.buffer[-i:].lower()):
                    keep_len = max(keep_len, i)
                    break

        if keep_len > 0:
            safe_buffer = self.buffer[:-keep_len]
        else:
            safe_buffer = self.buffer

        unclosed_idx = self.find_first_unclosed_tag_index(safe_buffer)
        
        if unclosed_idx is not None:
            yield_part = safe_buffer[:unclosed_idx]
            cleaned_yield = self.clean_text(yield_part)
            self.buffer = self.buffer[unclosed_idx:]
            return cleaned_yield
        else:
            cleaned_yield = self.clean_text(safe_buffer)
            if keep_len > 0:
                self.buffer = self.buffer[-keep_len:]
            else:
                self.buffer = ""
            return cleaned_yield

    def flush(self) -> str:
        """Returns any remaining buffered text, fully cleaned."""
        if self.buffer:
            final_cleaned = self.clean_text(self.buffer)
            self.buffer = ""
            return final_cleaned
        return ""

    async def stream_filter(self, token_generator: AsyncGenerator[str, None]) -> AsyncGenerator[str, None]:
        """Asynchronously cleans and yields tokens while filtering out leaky structures."""
        async for chunk in token_generator:
            safe = self.process_chunk(chunk)
            if safe:
                yield safe
        
        final = self.flush()
        if final:
            yield final
