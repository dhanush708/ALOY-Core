import sqlite3
import logging
from typing import Dict, Any
from tools.base import BaseTool, ToolMetadata

logger = logging.getLogger(__name__)

class SQLiteTool(BaseTool):
    """Tool for executing queries on a SQLite database, supporting dry-runs via transaction rollback."""
    
    def __init__(self):
        metadata = ToolMetadata(
            name="sqlite",
            description="Execute SQL queries against a SQLite database file in the workspace.",
            category=["Database"],
            parameters={
                "type": "object",
                "properties": {
                    "db_path": {
                        "type": "string",
                        "description": "Path to the SQLite database file relative to the workspace root."
                    },
                    "query": {
                        "type": "string",
                        "description": "The SQL query to execute."
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Simulate the query by executing within a transaction and rolling it back.",
                        "default": False
                    }
                },
                "required": ["db_path", "query"]
            },
            permissions_required=["write_file"], # SQLite writes write to files
            timeout_seconds=15,
            supports_dry_run=True
        )
        super().__init__(metadata)
        
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> str:
        db_path = params["db_path"]
        query = params["query"]
        dry_run = params.get("dry_run", False)
        
        # Connect to SQLite database
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        try:
            if dry_run:
                # For dry_run, we execute within a transaction and then rollback
                conn.execute("BEGIN TRANSACTION;")
                cursor = conn.cursor()
                cursor.execute(query)
                rows = cursor.fetchall()
                conn.rollback()
                
                res = [dict(r) for r in rows]
                return f"[Dry-Run Simulation Successful - Changes Rolled Back]\nQuery output:\n{res}"
            else:
                cursor = conn.cursor()
                cursor.execute(query)
                
                # Check if it was a modification query
                if cursor.description is None:
                    # No results description = statement did not return rows (e.g. INSERT, UPDATE, CREATE)
                    conn.commit()
                    return f"Query executed successfully. Rows affected: {cursor.rowcount}"
                else:
                    rows = cursor.fetchall()
                    conn.commit()
                    res = [dict(r) for r in rows]
                    import json
                    return json.dumps(res, indent=2)
                    
        except Exception as e:
            if dry_run:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.error(f"SQLite query failed: {query}. Error: {e}")
            raise
        finally:
            conn.close()
