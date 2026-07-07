import logging
import json
from ..pipeline import LearningContext, LearningPipelineStage, LearningCandidate

logger = logging.getLogger(__name__)

class ExtractionStage(LearningPipelineStage):
    """Extracts observations, understandings, and insights from conversation."""
    
    def __init__(self, model_router):
        self.model_router = model_router
        
    async def process(self, context: LearningContext) -> LearningContext:
        history_text = "\n".join([f"{m.get('role', 'unknown')}: {m.get('content', '')}" for m in context.history])
        
        prompt = f"""
Analyze the following conversation and extract:
1. Observations: Concrete facts about the user.
2. Understandings: Deductions from those facts.
3. Insights: Higher-level patterns.

Output JSON only in this format:
{{
  "observations": [{{"content": "...", "confidence": 0.9}}],
  "understandings": [{{"content": "...", "confidence": 0.8}}],
  "insights": [{{"content": "...", "confidence": 0.7}}]
}}

Conversation:
{history_text}
"""
        
        try:
            # We use the model router for LLM calls to respect budget and model availability
            response = await self.model_router.generate("qwen3:8b", prompt)
            
            # Very basic extraction (in reality would need robust JSON parsing)
            try:
                # Strip potential markdown blocks
                if "```json" in response:
                    response = response.split("```json")[1].split("```")[0]
                elif "```" in response:
                    response = response.split("```")[1].split("```")[0]
                    
                data = json.loads(response)
                
                for obs in data.get("observations", []):
                    context.candidates.append(LearningCandidate(content=obs["content"], type="observation", confidence=obs.get("confidence", 0.8)))
                for und in data.get("understandings", []):
                    context.candidates.append(LearningCandidate(content=und["content"], type="understanding", confidence=und.get("confidence", 0.7)))
                for ins in data.get("insights", []):
                    context.candidates.append(LearningCandidate(content=ins["content"], type="insight", confidence=ins.get("confidence", 0.6)))
                    
                context.extracted = True
            except json.JSONDecodeError:
                logger.error("Failed to parse extraction response")
                context.should_skip = True
                context.skip_reason = "JSON parse error"
                
        except Exception as e:
            logger.error(f"Extraction error: {e}")
            context.should_skip = True
            context.skip_reason = f"LLM error: {e}"
            
        return context
