import logging
from .prompts import PromptRegistry

logger = logging.getLogger(__name__)

class PromptLoader:
    """Loads default prompts into the registry."""
    
    def __init__(self, registry: PromptRegistry):
        self.registry = registry
        
    async def load_defaults(self):
        """Load the baseline prompts."""
        
        self.registry.register(
            name="system.identity",
            version="1.0",
            template=(
                "You are ALOY, an advanced AI Operating System and companion.\n"
                "You are highly intelligent, concise, and helpful.\n"
                "Current time: {current_time}"
            ),
            variables=["current_time"],
            model_hint="phi4-mini",
            metadata={"description": "Base identity prompt included in all contexts."}
        )
        
        self.registry.register(
            name="intent.classify",
            version="1.0",
            template=(
                "Classify the intent of the following user message.\n"
                "Possible intents: simple_chat, complex_chat, coding_request, reasoning_request, planning_request, memory_query, tool_request.\n\n"
                "User Message:\n{message}\n\n"
                "Reply with ONLY the exact intent string."
            ),
            variables=["message"],
            model_hint="phi4-mini",
            metadata={"description": "Intent classification fallback prompt."}
        )
        
        self.registry.register(
            name="learning.observe",
            version="1.0",
            template=(
                "Analyze the following conversation and extract concrete OBSERVATIONS about the user or the project.\n"
                "Output JSON format only:\n"
                "{{\n"
                "  \"observations\": [{{\"content\": \"...\", \"confidence\": 0.9}}]\n"
                "}}\n"
                "Confidence should be between 0.0 and 1.0.\n"
                "Conversation:\n{history}\n"
            ),
            variables=["history"],
            model_hint="qwen3:8b",
            metadata={"description": "Extract observations with confidence."}
        )
        
        self.registry.register(
            name="learning.analyze",
            version="1.0",
            template=(
                "Analyze the following conversation and extract logical UNDERSTANDINGS based on the facts.\n"
                "Output JSON format only:\n"
                "{{\n"
                "  \"understandings\": [{{\"content\": \"...\", \"confidence\": 0.8}}]\n"
                "}}\n"
                "Confidence should be between 0.0 and 1.0.\n"
                "Conversation:\n{history}\n"
            ),
            variables=["history"],
            model_hint="qwen3:8b",
            metadata={"description": "Extract understandings with confidence."}
        )

        # Reasoning Engine Prompts
        self.registry.register(
            name="reasoning.simple",
            version="1.0",
            template="Perform a direct reasoning analysis on the following query: '{query}'",
            variables=["query"],
            model_hint="qwen3:8b",
            metadata={"description": "Simple reasoning prompt."}
        )

        self.registry.register(
            name="reasoning.clarify",
            version="1.0",
            template="Given query: '{query}' and context: '{context}', clarify the requirements, constraints, and success criteria.",
            variables=["query", "context"],
            model_hint="qwen3:14b",
            metadata={"description": "Clarify requirements stage."}
        )

        self.registry.register(
            name="reasoning.design",
            version="1.0",
            template="Given query: '{query}', context: '{context}', and clarification: '{clarification}', design a robust strategy or architecture.",
            variables=["query", "context", "clarification"],
            model_hint="qwen3:14b",
            metadata={"description": "Design strategy/architecture stage."}
        )

        self.registry.register(
            name="reasoning.critique",
            version="1.0",
            template="Given query: '{query}', context: '{context}', and design: '{strategy}', identify risks, potential bugs, safety concerns, or missing edge cases.",
            variables=["query", "context", "strategy"],
            model_hint="qwen3:14b",
            metadata={"description": "Critique design stage."}
        )

        self.registry.register(
            name="reasoning.formulate",
            version="1.0",
            template="Given query: '{query}', design: '{design}', and critique: '{critique}', formulate the final detailed plan or response.",
            variables=["query", "design", "critique"],
            model_hint="qwen3:14b",
            metadata={"description": "Formulate final plan stage."}
        )

        self.registry.register(
            name="reasoning.verifier",
            version="1.0",
            template=(
                "Perform a logical verification on the generated output for query: '{query}'.\n"
                "Output:\n{output}\n\n"
                "Identify:\n"
                "1. Logical contradictions\n"
                "2. Missing assumptions\n"
                "3. Hallucination risk (0.0 to 1.0)\n"
                "4. Incomplete reasoning\n"
                "5. Confidence score (0.0 to 1.0)\n\n"
                "Return JSON only with keys: logical_contradictions (list of strings), missing_assumptions (list of strings), hallucination_risk (float), incomplete_reasoning (list of strings), confidence_score (float), recommendations (list of strings)."
            ),
            variables=["query", "output"],
            model_hint="qwen3:14b",
            metadata={"description": "Verification of final output."}
        )

        self.registry.register(
            name="reasoning.debate_creator",
            version="1.0",
            template="Given query: '{query}' and context: '{context}', propose a creative and solid solution. Previous critique if any: '{critic_response}'",
            variables=["query", "context", "critic_response"],
            model_hint="qwen3:14b",
            metadata={"description": "Debate creator perspective."}
        )

        self.registry.register(
            name="reasoning.debate_critic",
            version="1.0",
            template="Critique the creator's proposal for query: '{query}'. Proposal: '{creator_response}'. Context: '{context}'",
            variables=["query", "context", "creator_response"],
            model_hint="qwen3:14b",
            metadata={"description": "Debate critic perspective."}
        )

        self.registry.register(
            name="reasoning.debate_synthesize",
            version="1.0",
            template="Synthesize a final consensus solution for query: '{query}' based on creator proposal: '{creator_response}' and critic feedback: '{critic_response}'. Context: '{context}'",
            variables=["query", "context", "creator_response", "critic_response"],
            model_hint="qwen3:14b",
            metadata={"description": "Debate synthesis."}
        )
        
        logger.info("Default prompts loaded into registry.")

