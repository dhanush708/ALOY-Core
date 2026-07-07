class ResultFormatter:
    """Formatter to clean, sanitize, and truncate tool execution outputs."""
    
    @staticmethod
    def format(output: str, max_bytes: int = 100 * 1024) -> str:
        """
        Formats and truncates output if it exceeds max_bytes.
        Appends a warning indicating how many bytes were truncated.
        """
        if not output:
            return ""
            
        # Encode to check raw byte size
        encoded = output.encode("utf-8", errors="replace")
        if len(encoded) <= max_bytes:
            return output
            
        truncated_bytes = len(encoded) - max_bytes
        # Slice the bytes and decode back, ignoring trailing partial character bytes
        truncated_str = encoded[:max_bytes].decode("utf-8", errors="ignore")
        
        return f"{truncated_str}\n\n[output truncated: {truncated_bytes} bytes]"
