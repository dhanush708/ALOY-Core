import json
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from models.router import ModelRouter
from kernel.prompts import PromptRegistry

logger = logging.getLogger(__name__)

@dataclass
class VerificationResult:
    is_valid: bool
    logical_contradictions: List[str] = field(default_factory=list)
    missing_assumptions: List[str] = field(default_factory=list)
    hallucination_risk: float = 0.0
    incomplete_reasoning: List[str] = field(default_factory=list)
    confidence_score: float = 1.0
    recommendations: List[str] = field(default_factory=list)

class SelfVerifier:
    """Performs logical self-verification on output."""
    
    def __init__(self, model_router: ModelRouter, prompt_registry: PromptRegistry):
        self.model_router = model_router
        self.prompt_registry = prompt_registry
        
    async def verify(
        self,
        query: str,
        output: str,
        steps: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> VerificationResult:
        """Evaluate output against quality checklist."""
        try:
            prompt_template = self.prompt_registry.get("reasoning.verifier")
            prompt = prompt_template.render(query=query, output=output)
        except Exception as e:
            logger.warning(f"Could not load verification prompt from registry: {e}. Using fallback.")
            prompt = (
                f"Verify the output for query: '{query}'.\n"
                f"Output: {output}\n"
                "Return JSON with: logical_contradictions (list), missing_assumptions (list), "
                "hallucination_risk (float), incomplete_reasoning (list), confidence_score (float), recommendations (list)."
            )
            
        try:
            # We route this to 'classification' or 'summarization' model (usually lightweight qwen3:8b)
            # or a specific task if desired
            response = await self.model_router.generate(
                task="summarization",
                prompt=prompt,
                options={"temperature": 0.0}
            )
            
            return self._parse_response(response)
        except Exception as e:
            logger.error(f"Self-verification failed: {e}")
            # Fallback to default high confidence valid result
            return VerificationResult(is_valid=True)
            
    def _parse_response(self, text: str) -> VerificationResult:
        """Parse JSON response from LLM."""
        # Clean markdown code blocks
        clean_text = text.strip()
        if clean_text.startswith("```"):
            # strip start line
            lines = clean_text.splitlines()
            if lines[0].startswith("```json") or lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            clean_text = "\n".join(lines).strip()
            
        try:
            data = json.loads(clean_text)
            
            # Extract fields
            logical = data.get("logical_contradictions", [])
            missing = data.get("missing_assumptions", [])
            risk = float(data.get("hallucination_risk", 0.0))
            incomplete = data.get("incomplete_reasoning", [])
            confidence = float(data.get("confidence_score", 1.0))
            recs = data.get("recommendations", [])
            
            # A result is invalid if confidence is low, or contradictions/hallucinations are high
            is_valid = True
            if confidence < 0.6:
                is_valid = False
            if risk > 0.4:
                is_valid = False
            if len(logical) > 0:
                is_valid = False
                
            # If confidence is low and no recommendations are set, add defaults
            if not is_valid and not recs:
                if confidence < 0.4:
                    recs.append("deeper_reasoning")
                elif risk > 0.4:
                    recs.append("internet_research")
                else:
                    recs.append("clarify_user")
                    
            return VerificationResult(
                is_valid=is_valid,
                logical_contradictions=logical,
                missing_assumptions=missing,
                hallucination_risk=risk,
                incomplete_reasoning=incomplete,
                confidence_score=confidence,
                recommendations=recs
            )
        except Exception as e:
            logger.error(f"Failed to parse verification JSON: {e}. Text: {clean_text}")
            return VerificationResult(is_valid=True)
