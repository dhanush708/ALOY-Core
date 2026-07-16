import os
import re
import logging
from typing import Dict, Any
from tools.base import BaseTool, ToolMetadata

logger = logging.getLogger(__name__)

class DiffEngineTool(BaseTool):
    """Tool for applying search-replace patch blocks to workspace files."""
    
    def __init__(self):
        metadata = ToolMetadata(
            name="diff_engine",
            description="Apply modifications to a file using Search/Replace blocks.",
            category=["Filesystem"],
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to modify relative to workspace root."
                    },
                    "patch": {
                        "type": "string",
                        "description": "Search/Replace blocks format:\n<<<<<<< SEARCH\n[old code]\n=======\n[new code]\n>>>>>>> REPLACE"
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Simulate applying the patch without writing changes to disk.",
                        "default": False
                    }
                },
                "required": ["path", "patch"]
            },
            permissions_required=["write_file"],
            timeout_seconds=10,
            supports_dry_run=True
        )
        super().__init__(metadata)
        
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> str:
        path = params["path"]
        patch = params["patch"]
        dry_run = params.get("dry_run", False)
        
        if not os.path.exists(path):
            raise FileNotFoundError(f"File not found: {path}")
            
        with open(path, "r", encoding="utf-8") as f:
            original_content = f.read()
            
        try:
            modified_content = self._apply_patch(original_content, patch)
        except Exception as e:
            logger.error(f"Failed to apply patch to {path}: {e}")
            raise ValueError(f"Patch application failed: {e}") from e
            
        if dry_run:
            # Return diff or summary
            return f"[Dry-Run] Patch applies successfully to {path}. File would change."
            
        with open(path, "w", encoding="utf-8") as f:
            f.write(modified_content)
            
        return f"Successfully applied patch to {path}"
        
    def _apply_patch(self, content: str, patch: str) -> str:
        # Search-replace parsing
        # Normalize line endings to avoid matching issues
        content_norm = content.replace("\r\n", "\n")
        patch_norm = patch.replace("\r\n", "\n")
        
        blocks = re.split(r'<<<<<<< SEARCH\n', patch_norm)
        if len(blocks) == 1:
            raise ValueError("Patch must contain <<<<<<< SEARCH ... ======= ... >>>>>>> REPLACE blocks.")
            
        modified_content = content_norm
        for block in blocks[1:]:
            parts = re.split(r'\n=======\n', block)
            if len(parts) != 2:
                raise ValueError("Invalid patch structure: missing '=======' line separator.")
                
            search_part, replace_block = parts
            
            replace_parts = re.split(r'\n>>>>>>> REPLACE', replace_block)
            if not replace_parts:
                raise ValueError("Invalid patch structure: missing '>>>>>>> REPLACE' line separator.")
            replace_part = replace_parts[0]
            
            # Attempt to locate and replace search block
            if search_part not in modified_content:
                # Let's log details of search mismatch
                raise ValueError(f"Search block not found in target file.\nSearch Content:\n{search_part}")
                
            modified_content = modified_content.replace(search_part, replace_part, 1)
            
        # Restore native line endings if Windows
        if os.name == 'nt':
            modified_content = modified_content.replace("\n", "\r\n")
            
        return modified_content
