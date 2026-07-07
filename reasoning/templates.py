from typing import Dict, Any, List

# Planning Templates for sequential chain reasoning
PLANNING_TEMPLATES = {
    "coding_plan": [
        {
            "name": "clarify",
            "prompt_name": "reasoning.clarify",
            "required_vars": ["query", "context"]
        },
        {
            "name": "design",
            "prompt_name": "reasoning.design",
            "required_vars": ["query", "context", "clarification"]
        },
        {
            "name": "critique",
            "prompt_name": "reasoning.critique",
            "required_vars": ["query", "context", "strategy"]
        },
        {
            "name": "formulate",
            "prompt_name": "reasoning.formulate",
            "required_vars": ["query", "design", "critique"]
        }
    ],
    "root_cause_analysis": [
        {
            "name": "clarify",
            "prompt_name": "reasoning.clarify",
            "required_vars": ["query", "context"]
        },
        {
            "name": "hypothesize",
            "prompt_name": "reasoning.design", # Re-use design prompt
            "required_vars": ["query", "context", "clarification"]
        },
        {
            "name": "critique",
            "prompt_name": "reasoning.critique",
            "required_vars": ["query", "context", "strategy"]
        },
        {
            "name": "formulate",
            "prompt_name": "reasoning.formulate",
            "required_vars": ["query", "design", "critique"]
        }
    ],
    "exploratory_analysis": [
        {
            "name": "clarify",
            "prompt_name": "reasoning.clarify",
            "required_vars": ["query", "context"]
        },
        {
            "name": "decompose",
            "prompt_name": "reasoning.design",
            "required_vars": ["query", "context", "clarification"]
        },
        {
            "name": "synthesize",
            "prompt_name": "reasoning.formulate",
            "required_vars": ["query", "design", "critique"] # Critique can be empty
        }
    ]
}

def detect_strategy_and_template(query: str, context: Dict[str, Any]) -> tuple[str, str]:
    """Heuristically select reasoning strategy and planning template."""
    lower = query.lower()
    
    # 1. Determine Strategy
    # Direct answer matches simple questions
    if len(query.split()) < 5 or any(k in lower for k in ["hello", "hi", "what time", "date"]):
        strategy = "direct_answer"
    elif any(k in lower for k in ["debate", "contrast", "argue", "oppose"]):
        strategy = "debate"
    elif any(k in lower for k in ["tree", "branches", "paths", "options"]):
        strategy = "tree_of_thought"
    elif any(k in lower for k in ["deep", "think", "r1"]):
        strategy = "deep_reasoning"
    else:
        strategy = "chain_of_thought"
        
    # 2. Determine Planning Template if chain_of_thought or planning is used
    if any(k in lower for k in ["code", "write", "function", "class", "refactor", "implement", "build"]):
        template = "coding_plan"
    elif any(k in lower for k in ["error", "fail", "bug", "crash", "trace", "exception"]):
        template = "root_cause_analysis"
    else:
        template = "exploratory_analysis"
        
    return strategy, template
