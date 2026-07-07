import os
from typing import Dict, Any
from tools.base import BaseTool, ToolMetadata

class FileEditorTool(BaseTool):
    """Tool for reading, writing, and appending to files with dry-run capabilities."""
    
    def __init__(self):
        metadata = ToolMetadata(
            name="file_editor",
            description="Read, write, or append text to files in the workspace.",
            category=["Filesystem"],
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file relative to the workspace root."
                    },
                    "action": {
                        "type": "string",
                        "enum": ["read", "write", "append"],
                        "description": "Action to perform on the file."
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write or append (required for write/append actions)."
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Simulate the write/append action without committing changes to disk.",
                        "default": False
                    }
                },
                "required": ["path", "action"]
            },
            permissions_required=["write_file"], # note: read actions don't require write permission in practice, but we declare it generally or check dynamically
            timeout_seconds=10,
            supports_dry_run=True
        )
        super().__init__(metadata)
        
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> str:
        path = params["path"]
        action = params["action"]
        content = params.get("content", "")
        dry_run = params.get("dry_run", False)
        
        # Note: Sandbox path checking has already run on params["path"] in ToolSystem.execute()
        
        if action == "read":
            if not os.path.exists(path):
                raise FileNotFoundError(f"File not found: {path}")
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
                
        elif action == "write":
            if dry_run:
                return f"[Dry-Run] Would write {len(content)} characters to {path}"
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully wrote {len(content)} characters to {path}"
            
        elif action == "append":
            if dry_run:
                return f"[Dry-Run] Would append {len(content)} characters to {path}"
            with open(path, "a", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully appended {len(content)} characters to {path}"
            
        else:
            raise ValueError(f"Unknown action: {action}")
