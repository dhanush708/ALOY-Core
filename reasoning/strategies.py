import re
import time
import logging
from typing import Dict, Any, List, Tuple
from models.router import ModelRouter
from kernel.prompts import PromptRegistry
from .templates import PLANNING_TEMPLATES

logger = logging.getLogger(__name__)

def parse_think_block(text: str) -> Tuple[str, str]:
    """Extract `<think>` block and final output from a model response."""
    match = re.search(r'<think>(.*?)</think>', text, re.DOTALL | re.IGNORECASE)
    if match:
        thought = match.group(1).strip()
        # Remove the think block from the text
        final_output = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE).strip()
        return thought, final_output
    return "", text

class ReasoningStrategies:
    """Implementations of various reasoning styles."""
    
    def __init__(self, model_router: ModelRouter, prompt_registry: PromptRegistry, publish_event_cb=None):
        self.model_router = model_router
        self.prompt_registry = prompt_registry
        self.publish_event_cb = publish_event_cb
        
    async def _publish_stage_event(self, event_type: str, stage_name: str, data: Dict[str, Any]):
        if self.publish_event_cb:
            await self.publish_event_cb(event_type, stage_name, data)

    # 1. Direct Answer
    async def direct_answer(
        self,
        query: str,
        context: Dict[str, Any],
        depth: str
    ) -> Dict[str, Any]:
        """Simple prompt execution."""
        start = time.perf_counter()
        
        # Route to simple_chat task
        response = await self.model_router.generate(
            task="simple_chat",
            prompt=query,
            options={"temperature": 0.2 if depth == "medium" else 0.0}
        )
        
        duration = (time.perf_counter() - start) * 1000
        return {
            "final_output": response,
            "thought": "Direct response generated without sequential stages.",
            "steps": [{
                "stage": "direct_answer",
                "thought": "Single turn execution.",
                "output": response,
                "duration_ms": duration
            }],
            "duration_ms": duration
        }

    # 2. Chain of Thought (Sequential stage templates)
    async def chain_of_thought(
        self,
        query: str,
        context: Dict[str, Any],
        depth: str,
        template_name: str = "exploratory_analysis"
    ) -> Dict[str, Any]:
        """Runs the sequential templates of reasoning stages."""
        start_total = time.perf_counter()
        
        stages = PLANNING_TEMPLATES.get(template_name, PLANNING_TEMPLATES["exploratory_analysis"])
        
        # Depth controls effort: limit stages for 'simple'
        if depth == "simple" and len(stages) > 2:
            stages = stages[:2] # Truncate effort
            
        steps = []
        outputs = {}
        
        for stage in stages:
            stage_name = stage["name"]
            prompt_name = stage["prompt_name"]
            
            await self._publish_stage_event("started", stage_name, {})
            
            # Map input variables for render
            kwargs = {}
            for var in stage["required_vars"]:
                if var == "query":
                    kwargs["query"] = query
                elif var == "context":
                    kwargs["context"] = str(context)
                elif var == "clarification":
                    kwargs["clarification"] = outputs.get("clarify", "")
                elif var == "strategy":
                    kwargs["strategy"] = outputs.get("design", outputs.get("decompose", ""))
                elif var == "design":
                    kwargs["design"] = outputs.get("design", outputs.get("decompose", ""))
                elif var == "critique":
                    kwargs["critique"] = outputs.get("critique", "")
                    
            try:
                prompt_template = self.prompt_registry.get(prompt_name)
                prompt = prompt_template.render(**kwargs)
            except Exception as e:
                logger.warning(f"Failed to render prompt {prompt_name}: {e}. Falling back to default.")
                prompt = f"Run stage {stage_name} for query: {query}. Prior outputs: {outputs}"
                
            start_stage = time.perf_counter()
            
            # We use 'planning_request' model for reasoning stages, or fallback based on depth
            task = "planning_request" if depth in ["medium", "deep"] else "simple_chat"
            response = await self.model_router.generate(
                task=task,
                prompt=prompt
            )
            
            duration_stage = (time.perf_counter() - start_stage) * 1000
            outputs[stage_name] = response
            
            steps.append({
                "stage": stage_name,
                "thought": f"Completed reasoning stage {stage_name}.",
                "output": response,
                "duration_ms": duration_stage
            })
            
            await self._publish_stage_event("completed", stage_name, {
                "output": response,
                "duration_ms": duration_stage
            })
            
        final_output = outputs.get(stages[-1]["name"], "")
        total_duration = (time.perf_counter() - start_total) * 1000
        
        # Compile CoT thought history
        cot_thought = "\n\n".join([f"=== STAGE: {s['stage']} ===\n{s['output']}" for s in steps[:-1]])
        
        return {
            "final_output": final_output,
            "thought": cot_thought,
            "steps": steps,
            "duration_ms": total_duration
        }

    # 3. Deep Reasoning (Deepseek-R1)
    async def deep_reasoning(
        self,
        query: str,
        context: Dict[str, Any],
        depth: str
    ) -> Dict[str, Any]:
        """Queries Deepseek-R1 reasoning model."""
        start = time.perf_counter()
        
        # Set max tokens or thinking options depending on depth
        options = {}
        if depth == "simple":
            options["max_tokens"] = 1000
        elif depth == "deep":
            options["max_tokens"] = 8000
            options["temperature"] = 0.5
            
        response = await self.model_router.generate(
            task="reasoning_request",
            prompt=query,
            options=options
        )
        
        thought, final_output = parse_think_block(response)
        duration = (time.perf_counter() - start) * 1000
        
        return {
            "final_output": final_output,
            "thought": thought or "Internal thinking processed.",
            "steps": [{
                "stage": "deep_reasoning_r1",
                "thought": thought,
                "output": final_output,
                "duration_ms": duration
            }],
            "duration_ms": duration
        }

    # 4. Tree of Thought (ToT)
    async def tree_of_thought(
        self,
        query: str,
        context: Dict[str, Any],
        depth: str
    ) -> Dict[str, Any]:
        """Explores multiple thought paths/branches."""
        start_total = time.perf_counter()
        
        # Step 1: Generate branches
        await self._publish_stage_event("started", "generate_branches", {})
        branches_prompt = (
            f"Generate 3 distinct, independent reasoning strategies to solve the following query:\n"
            f"Query: '{query}'\n"
            f"Context: {context}\n\n"
            "Format your response as:\n"
            "BRANCH 1: [Short name] - [Description]\n"
            "BRANCH 2: [Short name] - [Description]\n"
            "BRANCH 3: [Short name] - [Description]"
        )
        
        start_branches = time.perf_counter()
        branches_text = await self.model_router.generate(task="planning_request", prompt=branches_prompt)
        duration_branches = (time.perf_counter() - start_branches) * 1000
        
        # Step 2: Evaluate branches
        await self._publish_stage_event("completed", "generate_branches", {"output": branches_text})
        await self._publish_stage_event("started", "evaluate_branches", {})
        
        eval_prompt = (
            f"Evaluate the feasibility, pros/cons, and success likelihood of these 3 proposed branches for query '{query}':\n"
            f"{branches_text}\n\n"
            "Select the single best branch and explain why."
        )
        start_eval = time.perf_counter()
        eval_text = await self.model_router.generate(task="planning_request", prompt=eval_prompt)
        duration_eval = (time.perf_counter() - start_eval) * 1000
        
        # Step 3: Execute chosen branch
        await self._publish_stage_event("completed", "evaluate_branches", {"output": eval_text})
        await self._publish_stage_event("started", "execute_best_branch", {})
        
        execute_prompt = (
            f"Solve the user query based on the selected best strategy from the evaluation.\n"
            f"Query: '{query}'\n"
            f"Branches:\n{branches_text}\n"
            f"Evaluation and Selection:\n{eval_text}\n\n"
            "Provide the final complete solution."
        )
        start_execute = time.perf_counter()
        final_solution = await self.model_router.generate(task="planning_request", prompt=execute_prompt)
        duration_execute = (time.perf_counter() - start_execute) * 1000
        await self._publish_stage_event("completed", "execute_best_branch", {"output": final_solution})
        
        total_duration = (time.perf_counter() - start_total) * 1000
        
        steps = [
            {"stage": "generate_branches", "thought": "Generated 3 reasoning paths.", "output": branches_text, "duration_ms": duration_branches},
            {"stage": "evaluate_branches", "thought": "Evaluated pros/cons of each path and selected best.", "output": eval_text, "duration_ms": duration_eval},
            {"stage": "execute_best_branch", "thought": "Executed final output using chosen path.", "output": final_solution, "duration_ms": duration_execute}
        ]
        
        thought_log = f"=== BRANCHES GENERATED ===\n{branches_text}\n\n=== PATH EVALUATION ===\n{eval_text}"
        
        return {
            "final_output": final_solution,
            "thought": thought_log,
            "steps": steps,
            "duration_ms": total_duration
        }

    # 5. Debate
    async def debate(
        self,
        query: str,
        context: Dict[str, Any],
        depth: str
    ) -> Dict[str, Any]:
        """Creator vs Critic debate sequence."""
        start_total = time.perf_counter()
        
        # Round 1: Creator proposal
        await self._publish_stage_event("started", "debate_creator_proposal", {})
        creator_prompt = self.prompt_registry.get("reasoning.debate_creator").render(
            query=query, context=str(context), critic_response="None"
        )
        start_creator = time.perf_counter()
        proposal = await self.model_router.generate(task="planning_request", prompt=creator_prompt)
        duration_creator = (time.perf_counter() - start_creator) * 1000
        await self._publish_stage_event("completed", "debate_creator_proposal", {"output": proposal})
        
        # Round 2: Critic critique
        await self._publish_stage_event("started", "debate_critic_feedback", {})
        critic_prompt = self.prompt_registry.get("reasoning.debate_critic").render(
            query=query, context=str(context), creator_response=proposal
        )
        start_critic = time.perf_counter()
        critique = await self.model_router.generate(task="planning_request", prompt=critic_prompt)
        duration_critic = (time.perf_counter() - start_critic) * 1000
        await self._publish_stage_event("completed", "debate_critic_feedback", {"output": critique})
        
        # Round 3: Synthesis
        await self._publish_stage_event("started", "debate_synthesis", {})
        synthesize_prompt = self.prompt_registry.get("reasoning.debate_synthesize").render(
            query=query, context=str(context), creator_response=proposal, critic_response=critique
        )
        start_synth = time.perf_counter()
        synthesis = await self.model_router.generate(task="planning_request", prompt=synthesize_prompt)
        duration_synth = (time.perf_counter() - start_synth) * 1000
        await self._publish_stage_event("completed", "debate_synthesis", {"output": synthesis})
        
        total_duration = (time.perf_counter() - start_total) * 1000
        
        steps = [
            {"stage": "debate_creator_proposal", "thought": "Creator proposed initial solution.", "output": proposal, "duration_ms": duration_creator},
            {"stage": "debate_critic_feedback", "thought": "Critic reviewed and highlighted flaws.", "output": critique, "duration_ms": duration_critic},
            {"stage": "debate_synthesis", "thought": "Synthesized creator and critic outputs into a consensus.", "output": synthesis, "duration_ms": duration_synth}
        ]
        
        thought_log = f"=== CREATOR SOLUTION ===\n{proposal}\n\n=== CRITIC FEEDBACK ===\n{critique}"
        
        return {
            "final_output": synthesis,
            "thought": thought_log,
            "steps": steps,
            "duration_ms": total_duration
        }

    # 6. Planning (Reuses Chain of Thought with coding_plan)
    async def planning(self, query: str, context: Dict[str, Any], depth: str) -> Dict[str, Any]:
        return await self.chain_of_thought(query, context, depth, template_name="coding_plan")

    # 7. Verification
    async def verification(self, query: str, context: Dict[str, Any], depth: str) -> Dict[str, Any]:
        """Performs simple verification as a reasoning strategy."""
        start = time.perf_counter()
        target_output = context.get("target_output", "")
        
        # Direct verification prompt
        prompt = self.prompt_registry.get("reasoning.verifier").render(query=query, output=target_output)
        response = await self.model_router.generate(task="planning_request", prompt=prompt)
        
        duration = (time.perf_counter() - start) * 1000
        return {
            "final_output": response,
            "thought": "Verified target output directly.",
            "steps": [{
                "stage": "verifier",
                "thought": "Run logic check.",
                "output": response,
                "duration_ms": duration
            }],
            "duration_ms": duration
        }

    # 8. Reflection
    async def reflection(self, query: str, context: Dict[str, Any], depth: str) -> Dict[str, Any] :
        """Reflect on prior errors/outcomes."""
        start = time.perf_counter()
        prior_error = context.get("prior_error", "None specified.")
        prior_attempt = context.get("prior_attempt", "None specified.")
        
        prompt = (
            f"Analyze this prior attempt and error to identify what went wrong and produce a corrected path.\n"
            f"Query: '{query}'\n"
            f"Prior Attempt: {prior_attempt}\n"
            f"Error / Feedback: {prior_error}\n\n"
            "State: 1) What went wrong, 2) The fix, 3) Corrected complete output."
        )
        response = await self.model_router.generate(task="planning_request", prompt=prompt)
        
        duration = (time.perf_counter() - start) * 1000
        return {
            "final_output": response,
            "thought": "Reflected on prior execution failure.",
            "steps": [{
                "stage": "reflection",
                "thought": "Deconstruct failure and regenerate solution.",
                "output": response,
                "duration_ms": duration
            }],
            "duration_ms": duration
        }
