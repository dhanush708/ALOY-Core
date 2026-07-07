import re
import uuid
import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from .issue_detector import IssueDetector
from .proposal import ImprovementProposal

logger = logging.getLogger(__name__)


class EvolutionAnalyzer:
    """Orchestrates scanning, analyzes issues, and uses ModelRouter to generate structured ImprovementProposals."""

    def __init__(self, db_pool, model_router, model_tracker=None):
        self.db_pool = db_pool
        self.model_router = model_router
        self.detector = IssueDetector(db_pool, model_tracker)

    async def scan_and_analyze(self) -> List[ImprovementProposal]:
        """Perform scan, generate proposals via LLM, and save them in DB as pending."""
        logger.info("Starting Evolution scan and analysis...")
        
        findings = self.detector.detect_all()
        proposals: List[ImprovementProposal] = []

        # 1. Process Repeated Failures
        for item in findings["repeated_failures"]:
            p = await self._generate_repeated_failure_proposal(item)
            if p:
                proposals.append(p)

        # 2. Process Semantic Overlaps
        for item in findings["semantic_overlaps"]:
            p = await self._generate_semantic_overlap_proposal(item)
            if p:
                proposals.append(p)

        # 3. Process Prompt Drift
        for item in findings["prompt_drift"]:
            p = await self._generate_prompt_drift_proposal(item)
            if p:
                proposals.append(p)

        # 4. Process Missing Packages
        for item in findings["missing_packages"]:
            p = await self._generate_missing_package_proposal(item)
            if p:
                proposals.append(p)

        # Save proposals in database
        if proposals:
            await self._save_proposals(proposals)

        logger.info(f"Evolution scan complete: generated {len(proposals)} proposals.")
        return proposals

    async def _generate_repeated_failure_proposal(self, item: Dict[str, Any]) -> ImprovementProposal:
        prompt = f"""You are ALOY's Evolution Engine Synthesis model.
Analyze the following repeated task failure from an autonomous agent:
Agent: {item['agent']}
Task Title: {item['task_title']}
Error Message: {item['error_message']}

Generate a structured Self-Improvement Proposal to fix this repeated bug/failure.
You MUST output your response in JSON format with these exact keys:
- "problem": Description of why this is failing.
- "evidence": Details / count of failures.
- "possible_solutions": List of possible approaches to fix it.
- "recommended_solution": The best technical approach.
- "affected_files": List of code files likely needing modification.
- "benefits": Value of fixing it.
- "risks": Risks of fixing it and how to mitigate them.
- "implementation_plan": Markdown step-by-step checklist plan (e.g. edit specific functions, run tests) to be executed by a Coding Agent.

JSON format:
{{
  "problem": "...",
  "evidence": "...",
  "possible_solutions": ["...", "..."],
  "recommended_solution": "...",
  "affected_files": ["..."],
  "benefits": "...",
  "risks": "...",
  "implementation_plan": "- [ ] Step 1\\n- [ ] Step 2"
}}
"""
        res = await self._call_llm_json(prompt)
        if not res:
            return None

        prop_id = f"FAIL_{uuid.uuid4().hex[:8].upper()}"
        return ImprovementProposal(
            id=prop_id,
            problem=res["problem"],
            evidence=item["evidence"],
            possible_solutions=res["possible_solutions"],
            recommended_solution=res["recommended_solution"],
            affected_files=res["affected_files"],
            benefits=res["benefits"],
            risks=res["risks"],
            implementation_plan=res["implementation_plan"],
            status="pending",
            metadata={"type": "repeated_failure", "agent": item["agent"], "task_title": item["task_title"]}
        )

    async def _generate_semantic_overlap_proposal(self, item: Dict[str, Any]) -> ImprovementProposal:
        prompt = f"""You are ALOY's Evolution Engine Synthesis model.
Analyze the following overlapping semantic/permanent memories that duplicate information:
Memory 1 content: "{item['content_1']}"
Memory 2 content: "{item['content_2']}"

Generate a structured Self-Improvement Proposal to consolidate/merge these memories into a single clean memory entry.
You MUST output your response in JSON format with these exact keys:
- "problem": Description of the duplication/overlap.
- "evidence": The overlapping texts and their Jaccard similarity score.
- "possible_solutions": List of possible ways to merge (e.g. keep one, merge into new).
- "recommended_solution": The exact consolidated text to keep in long_term/permanent memory.
- "affected_files": List containing the target database or system components (e.g. ["database:memories"]).
- "benefits": Decluttering memory and reducing context token sizes.
- "risks": Loss of nuance in one of the memories.
- "implementation_plan": Markdown steps outlining how to run the consolidation.

JSON format:
{{
  "problem": "...",
  "evidence": "...",
  "possible_solutions": ["...", "..."],
  "recommended_solution": "...",
  "affected_files": ["database:memories"],
  "benefits": "...",
  "risks": "...",
  "implementation_plan": "- [ ] Delete old memories\\n- [ ] Store recommended consolidated content"
}}
"""
        res = await self._call_llm_json(prompt)
        if not res:
            return None

        prop_id = f"MEM_{uuid.uuid4().hex[:8].upper()}"
        return ImprovementProposal(
            id=prop_id,
            problem=res["problem"],
            evidence=item["evidence"],
            possible_solutions=res["possible_solutions"],
            recommended_solution=res["recommended_solution"],
            affected_files=res["affected_files"],
            benefits=res["benefits"],
            risks=res["risks"],
            implementation_plan=res["implementation_plan"],
            status="pending",
            metadata={
                "type": "semantic_overlap",
                "memory_id_1": item["memory_id_1"],
                "memory_id_2": item["memory_id_2"],
                "consolidated_content": res["recommended_solution"]
            }
        )

    async def _generate_prompt_drift_proposal(self, item: Dict[str, Any]) -> ImprovementProposal:
        prompt = f"""You are ALOY's Evolution Engine Synthesis model.
Analyze the degraded model execution or telemetry metrics indicating potential prompt drift:
Model: {item['model']}
Task: {item['task']}
Evidence Context: {item['evidence']}

Generate a structured Self-Improvement Proposal to update or optimize the prompt registry template for task '{item['task']}'.
You MUST output your response in JSON format with these exact keys:
- "problem": Description of the performance degradation or drift.
- "evidence": Telemetry latency/error rate stats.
- "possible_solutions": List of suggested prompts modifications.
- "recommended_solution": A revised/improved prompt registry template instruction text.
- "affected_files": List of prompt files or databases (e.g. ["database:prompts"]).
- "benefits": Improved response accuracy and lower latencies.
- "risks": Compatibility with existing router expectations.
- "implementation_plan": Markdown steps outlining how to register the new template.

JSON format:
{{
  "problem": "...",
  "evidence": "...",
  "possible_solutions": ["...", "..."],
  "recommended_solution": "...",
  "affected_files": ["database:prompts"],
  "benefits": "...",
  "risks": "...",
  "implementation_plan": "- [ ] Register optimized template in PromptRegistry"
}}
"""
        res = await self._call_llm_json(prompt)
        if not res:
            return None

        prop_id = f"PRMPT_{uuid.uuid4().hex[:8].upper()}"
        return ImprovementProposal(
            id=prop_id,
            problem=res["problem"],
            evidence=item["evidence"],
            possible_solutions=res["possible_solutions"],
            recommended_solution=res["recommended_solution"],
            affected_files=res["affected_files"],
            benefits=res["benefits"],
            risks=res["risks"],
            implementation_plan=res["implementation_plan"],
            status="pending",
            metadata={
                "type": "prompt_drift",
                "target_prompt_name": item["task"],
                "optimized_template": res["recommended_solution"]
            }
        )

    async def _generate_missing_package_proposal(self, item: Dict[str, Any]) -> ImprovementProposal:
        prompt = f"""You are ALOY's Evolution Engine Synthesis model.
Analyze the following missing dependency issue:
Package Name: {item['package_name']}
System: {item['system']} (e.g. python, node)
Evidence Context: {item['evidence']}

Generate a structured Self-Improvement Proposal to install the missing package and add it to dependency manifests (requirements.txt or package.json).
You MUST output your response in JSON format with these exact keys:
- "problem": Description of missing library.
- "evidence": ImportError / ModuleNotFoundError details.
- "possible_solutions": List of ways to obtain it (e.g., pip install, npm install).
- "recommended_solution": Command to run (e.g. "pip install {item['package_name']}").
- "affected_files": Dependency files (e.g. ["requirements.txt"] or ["package.json"]).
- "benefits": Enable failed tasks to execute correctly.
- "risks": Dependency conflicts or license compatibility.
- "implementation_plan": Markdown steps (e.g. - [ ] run pip install package_name\n- [ ] update requirements.txt).

JSON format:
{{
  "problem": "...",
  "evidence": "...",
  "possible_solutions": ["...", "..."],
  "recommended_solution": "pip install {item['package_name']}",
  "affected_files": ["requirements.txt"],
  "benefits": "...",
  "risks": "...",
  "implementation_plan": "- [ ] Run pip install\\n- [ ] Add dependency to requirements.txt"
}}
"""
        res = await self._call_llm_json(prompt)
        if not res:
            return None

        prop_id = f"PKG_{uuid.uuid4().hex[:8].upper()}"
        return ImprovementProposal(
            id=prop_id,
            problem=res["problem"],
            evidence=item["evidence"],
            possible_solutions=res["possible_solutions"],
            recommended_solution=res["recommended_solution"],
            affected_files=res["affected_files"],
            benefits=res["benefits"],
            risks=res["risks"],
            implementation_plan=res["implementation_plan"],
            status="pending",
            metadata={
                "type": "missing_package",
                "package_name": item["package_name"],
                "system": item["system"],
                "install_command": res["recommended_solution"]
            }
        )

    async def _call_llm_json(self, prompt: str) -> Optional[Dict[str, Any]]:
        try:
            response = await self.model_router.generate("summarization", prompt)
            response = response.strip()
            # Extract JSON block
            match = re.search(r'\{[\s\S]*\}', response)
            if match:
                return json.loads(match.group(0))
            else:
                # Fallback parse if formatting is weird
                return json.loads(response)
        except Exception as e:
            logger.error(f"Failed to generate synthesis proposal: {e}")
            return None

    async def _save_proposals(self, proposals: List[ImprovementProposal]):
        """Persist proposals in sqlite database."""
        query = """
            INSERT OR REPLACE INTO evolution_proposals (
                id, problem, evidence, possible_solutions, recommended_solution,
                affected_files, benefits, risks, implementation_plan, status, created_at, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        try:
            with self.db_pool.get_write_connection() as conn:
                for p in proposals:
                    conn.execute(
                        query,
                        (
                            p.id,
                            p.problem,
                            p.evidence,
                            json.dumps(p.possible_solutions),
                            p.recommended_solution,
                            json.dumps(p.affected_files),
                            p.benefits,
                            p.risks,
                            p.implementation_plan,
                            p.status,
                            p.created_at,
                            json.dumps(p.metadata)
                        )
                    )
        except Exception as e:
            logger.error(f"Failed to save evolution proposals: {e}")
