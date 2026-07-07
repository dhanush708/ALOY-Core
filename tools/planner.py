import json
import logging
from dataclasses import dataclass
from typing import Dict, Any, Optional

from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

@dataclass
class ToolCall:
    tool_name: str
    params: Dict[str, Any]

class ToolPlanner:
    """Uses LLM reasoning through ModelRouter to intelligently select and configure tools."""
    
    def __init__(self, registry: ToolRegistry, model_router):
        self._registry = registry
        self._model_router = model_router
        
    async def select(self, task_description: str, context: Optional[Dict[str, Any]] = None) -> Optional[ToolCall]:
        """
        Select a tool and populate its parameters based on the task description.
        Returns a ToolCall if a tool is chosen, otherwise returns None.
        """
        ctx = context or {}
        session_id = ctx.get("session_id")
        
        metadata_list = self._registry.list_all_metadata()
        
        # Serialize tool schemas
        schemas = []
        for meta in metadata_list:
            schemas.append({
                "name": meta.name,
                "description": meta.description,
                "category": meta.category,
                "parameters": meta.parameters
            })
            
        schemas_json = json.dumps(schemas, indent=2)
        
        prompt = f"""You are the tool selection planner for ALOY. Your task is to analyze the user request and determine the single most appropriate tool and the correct parameters to call.

Available Tools:
{schemas_json}

User Request:
{task_description}

You must respond in raw JSON format with the following structure:
{{
  "tool": "name_of_selected_tool",
  "params": {{
    "param_name": "param_value",
    ...
  }}
}}

If no tool is appropriate or necessary, respond with:
{{
  "tool": null,
  "params": {{}}
}}

Respond with raw JSON only. Do not include markdown code block syntax (like ```json), explanations, or trailing whitespace.
"""

        try:
            response = await self._model_router.generate(
                task="tool_request",
                prompt=prompt,
                conversation_id=session_id
            )
            
            # Clean up potential markdown formatting wrapping the JSON response
            clean_res = response.strip()
            if clean_res.startswith("```json"):
                clean_res = clean_res[7:]
            elif clean_res.startswith("```"):
                clean_res = clean_res[3:]
            if clean_res.endswith("```"):
                clean_res = clean_res[:-3]
            clean_res = clean_res.strip()
            
            data = json.loads(clean_res)
            tool_name = data.get("tool")
            params = data.get("params", {})
            
            if not tool_name:
                return None
                
            return ToolCall(tool_name=tool_name, params=params)
            
        except Exception as e:
            logger.error(f"Error in ToolPlanner selection: {e}. Model response was: {response if 'response' in locals() else 'None'}")
            return None
