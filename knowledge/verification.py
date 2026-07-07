import logging
import json
import re
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class SourceVerifier:
    """Uses LLM to verify search evidence quality, filter bias, and compute confidence."""

    def __init__(self, model_router):
        self.model_router = model_router

    async def verify(self, query: str, snippets: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Verify quality of fetched results and return a structured rating and answer."""
        if not snippets:
            return {
                "answer": "No research evidence found.",
                "confidence_score": 0.0,
                "source_quality": "low",
                "lessons_learned": "Expand queries or check connection."
            }

        snippets_text = ""
        for idx, s in enumerate(snippets):
            snippets_text += f"\n--- Source {idx+1}: {s.get('title', 'Unknown')} ({s.get('url', 'no-url')}) ---\n{s.get('snippet', '')}\n"

        prompt = f"""You are ALOY's Research Source Verifier. 
Analyze the query and the following retrieved snippets. Evaluate evidence quality, filter bias or outdated content, and synthesize a final verified answer.
Also, assign a confidence score between 0.0 and 1.0 (where 1.0 is extremely high quality/certainty and 0.0 is completely untrusted).

Query: {query}

Retrieved Snippets:
{snippets_text}

Generate your response in JSON format with these keys:
- "answer": A concise verified technical answer.
- "confidence_score": Float between 0.0 and 1.0.
- "source_quality": "high", "medium", or "low".
- "lessons_learned": A key takeaway or lesson from the research context.

JSON format:
{{
   "answer": "...",
   "confidence_score": 0.85,
   "source_quality": "high",
   "lessons_learned": "..."
}}
"""

        try:
            llm_response = await self.model_router.generate(
                task="meta_request",
                prompt=prompt
            )
            result = self._parse_json(llm_response)
            return result
        except Exception as e:
            logger.error(f"Source verification failed: {e}")
            return {
                "answer": f"Failed to verify research context: {e}",
                "confidence_score": 0.3,
                "source_quality": "low",
                "lessons_learned": "Error invoking model."
            }

    def _parse_json(self, text: str) -> Dict[str, Any]:
        """Extract and parse JSON block from string."""
        text = text.strip()
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                data = json.loads(match.group(0))
                if "confidence_score" in data:
                    data["confidence_score"] = float(data["confidence_score"])
                return data
            except (json.JSONDecodeError, ValueError):
                pass
        return {
            "answer": text,
            "confidence_score": 0.5,
            "source_quality": "medium",
            "lessons_learned": "Parsed from unstructured text."
        }
