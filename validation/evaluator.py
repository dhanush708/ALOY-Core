import re
from typing import Dict, Any, List

ROBOTIC_FILLERS = [
    r"\bcertainly\b",
    r"\bit should be noted\b",
    r"\baccording to\b",
    r"\bi recommend\b",
    r"\bas an ai\b",
    r"\bthis can be achieved\b"
]

def evaluate_response(
    category: str,
    prompt: str,
    response_text: str,
    context: Any,
    latency_ms: float
) -> Dict[str, Any]:
    """Evaluates the LLM response against expected quality, identity, RAG, and routing rules."""
    response_lower = response_text.lower()
    
    # 1. Identity Accuracy
    identity_score = 100
    identity_fails = []
    
    if category == "identity":
        if "aloy" not in response_lower:
            identity_score -= 30
            identity_fails.append("Failed to claim ALOY identity.")
        if "1.0" not in response_text:
            identity_score -= 30
            identity_fails.append("Failed to claim version 1.0.")
        for competitor in ["gpt", "phi-4", "phi4", "deepseek", "qwen", "openai"]:
            if competitor in response_lower:
                # Exclude occurrences of Dhanush's github or email containing github/gmail
                if competitor == "openai" and "openai" in response_lower:
                    identity_score -= 50
                    identity_fails.append("Claimed competitor identity (OpenAI).")
                elif competitor in ["phi-4", "phi4", "deepseek", "qwen"]:
                    identity_score -= 50
                    identity_fails.append(f"Claimed competitor model ({competitor}).")
                    
    identity_score = max(0, identity_score)
    
    # 2. Memory Accuracy
    memory_score = 100
    memory_fails = []
    if category == "memory":
        # Check if model properly handles empty context or seeded values
        has_memories = len(getattr(context, "memories", [])) > 0
        if not has_memories:
            # Should admit it doesn't know rather than fabricating details
            admit_phrases = ["don't know", "do not know", "don't remember", "not in my memory", "no stored information", "haven't told me"]
            if not any(phrase in response_lower for phrase in admit_phrases):
                memory_score -= 50
                memory_fails.append("Did not admit lack of memory when context was empty.")
                
    # 3. Search Accuracy
    search_score = 100
    search_fails = []
    search_triggered = getattr(context, "search_triggered", False)
    search_succeeded = getattr(context, "search_succeeded", False)
    
    # Check if category requires search
    requires_search = category in ["internet_search", "latest_news", "games"]
    if requires_search:
        if not search_triggered:
            search_score -= 50
            search_fails.append("Did not trigger search when required.")
        elif not search_succeeded:
            # Search failed: should contain warning/cancellation
            if "unable to retrieve" not in response_text and "search failed" not in response_lower:
                search_score -= 50
                search_fails.append("Failed to gracefully report failed search.")
    else:
        if search_triggered:
            search_score -= 40
            search_fails.append("Triggered redundant web search for non-live request.")
            
    # 4. Hallucination Risk
    hallucination_score = 100
    hallucination_fails = []
    if category == "hallucination":
        # Check for predictions or future-guessing
        predictive_phrases = ["will win", "is predicted to", "announced that it will", "according to predictions"]
        if any(phrase in response_lower for phrase in predictive_phrases):
            hallucination_score -= 50
            hallucination_fails.append("Speculated on future prediction.")
        if "nobody knows" not in response_lower and "cannot answer" not in response_lower:
            # Check if it fabricated any details for year > 2026
            year_match = re.search(r"\b(202[7-9]|20[3-9]\d)\b", prompt)
            if year_match and not any(k in response_lower for k in ["unknown", "not release", "nobody knows", "future", "cannot predict"]):
                hallucination_score -= 60
                hallucination_fails.append(f"Fabricated details for future year {year_match.group(0)}.")
                
    hallucination_score = max(0, hallucination_score)

    # 5. Conversation Quality & Naturalness
    naturalness_score = 100
    quality_fails = []
    for filler in ROBOTIC_FILLERS:
        if re.search(filler, response_lower):
            naturalness_score -= 25
            quality_fails.append(f"Used robotic filler matching pattern '{filler}'.")
            
    naturalness_score = max(0, naturalness_score)
    
    # 6. Reasoning Quality
    reasoning_score = 100
    reasoning_fails = []
    if category == "reasoning":
        # Check if reasoning context or step logs exist
        has_steps = len(getattr(context, "reasoning_steps", [])) > 0 or "<think>" in response_text or "Correction Pass" in response_text
        if not has_steps and "explain" in prompt.lower():
            reasoning_score -= 40
            reasoning_fails.append("Completed reasoning request without reasoning steps or thought blocks.")
            
    # 7. Routing Correctness
    routing_score = 100
    routing_fails = []
    model_used = getattr(context, "model", "unknown")
    intent = getattr(context, "intent", "unknown")
    
    # Simple tasks should use phi4-mini
    if intent in ["simple_chat", "memory_query", "meta_request"]:
        if "phi4" not in model_used.lower() and "mini" not in model_used.lower() and model_used != "unknown":
            routing_score -= 50
            routing_fails.append(f"Used heavy model '{model_used}' for lightweight intent '{intent}'.")
    # Complex tasks should use qwen3
    elif intent in ["coding_request", "reasoning_request"]:
        if "qwen" not in model_used.lower() and model_used != "unknown":
            routing_score -= 50
            routing_fails.append(f"Used lightweight model '{model_used}' for heavy intent '{intent}'.")

    # 8. Latency Score
    if latency_ms < 150:
        latency_score = 100
    else:
        # Deduct 10 points for every 150ms of overhead
        latency_score = max(0, 100 - int((latency_ms - 150) / 15))

    # Compile all failure logs
    all_fails = identity_fails + memory_fails + search_fails + hallucination_fails + quality_fails + reasoning_fails + routing_fails
    passed = len(all_fails) == 0
    severity = "Low"
    if any("competitor" in f or "Fabricated" in f for f in all_fails):
        severity = "Critical"
    elif any("Did not trigger search" in f or "heavy model" in f for f in all_fails):
        severity = "High"
    elif len(all_fails) > 0:
        severity = "Medium"
        
    # Calculate weighted overall score
    overall_score = int(
        (identity_score * 0.15) +
        (memory_score * 0.15) +
        (search_score * 0.15) +
        (hallucination_score * 0.20) +
        (naturalness_score * 0.15) +
        (reasoning_score * 0.10) +
        (routing_score * 0.10)
    )

    return {
        "passed": passed,
        "overall_score": overall_score,
        "scores": {
            "identity": identity_score,
            "memory": memory_score,
            "search": search_score,
            "hallucination": hallucination_score,
            "naturalness": naturalness_score,
            "reasoning": reasoning_score,
            "routing": routing_score,
            "latency": latency_score
        },
        "failures": all_fails,
        "severity": severity if not passed else "None",
        "intent": intent,
        "model": model_used,
        "search_triggered": search_triggered,
        "search_succeeded": search_succeeded,
        "latency_ms": latency_ms
    }
