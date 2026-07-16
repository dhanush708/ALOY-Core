import os
import sys
import json
import logging
import subprocess
from datetime import datetime, timezone
from typing import Optional

CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

from .proposal import ImprovementProposal

logger = logging.getLogger(__name__)


class ReviewGate:
    """Blocks automatic changes. Handles user approval/rejection and applies proposed actions."""

    def __init__(self, db_pool, memory_manager, prompt_registry=None, agent_runtime=None):
        self.db_pool = db_pool
        self.memory_manager = memory_manager
        self.prompt_registry = prompt_registry
        self.agent_runtime = agent_runtime

    async def approve_proposal(self, proposal_id: str) -> bool:
        """Approves and executes a proposal based on its type."""
        logger.info(f"Approving proposal {proposal_id}...")

        # 1. Fetch proposal from DB
        proposal = await self._get_proposal(proposal_id)
        if not proposal:
            logger.error(f"Proposal {proposal_id} not found.")
            return False

        if proposal.status != "pending":
            logger.warning(f"Proposal {proposal_id} is already in state: {proposal.status}")
            return False

        # 2. Update status to approved
        await self._update_status(proposal_id, "approved")

        # 3. Apply the recommended solution
        success = False
        try:
            prop_type = proposal.metadata.get("type")
            if prop_type == "repeated_failure":
                success = await self._apply_repeated_failure(proposal)
            elif prop_type == "semantic_overlap":
                success = await self._apply_semantic_overlap(proposal)
            elif prop_type == "prompt_drift":
                success = await self._apply_prompt_drift(proposal)
            elif prop_type == "missing_package":
                success = await self._apply_missing_package(proposal)
            else:
                logger.error(f"Unknown proposal type: {prop_type}")
                success = False
        except Exception as e:
            logger.error(f"Failed to apply proposal {proposal_id}: {e}", exc_info=True)
            success = False

        # 4. Set final status
        final_status = "applied" if success else "failed"
        await self._update_status(proposal_id, final_status)
        return success

    async def reject_proposal(self, proposal_id: str) -> bool:
        """Rejects a proposal."""
        logger.info(f"Rejecting proposal {proposal_id}...")
        proposal = await self._get_proposal(proposal_id)
        if not proposal:
            return False
        if proposal.status != "pending":
            return False
        await self._update_status(proposal_id, "rejected")
        return True

    async def _apply_repeated_failure(self, proposal: ImprovementProposal) -> bool:
        """Trigger an AgentRuntime session to perform the recommended fix."""
        if not self.agent_runtime:
            logger.error("AgentRuntime not set in ReviewGate. Cannot apply repeated failure proposal.")
            return False

        # Resolve project ID
        with self.db_pool.get_read_connection() as conn:
            proj_row = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()
        
        if not proj_row:
            logger.error("No active projects found. Cannot spawn Agent Session.")
            return False

        project_id = proj_row["id"]
        goal = (
            f"Fix repeated failure: {proposal.metadata.get('task_title')}. "
            f"Implementation Plan:\n{proposal.implementation_plan}\n"
            f"Recommended Solution: {proposal.recommended_solution}"
        )
        try:
            session_id = await self.agent_runtime.start_session(goal=goal, project_id=project_id)
            # Run execution asynchronously in a background task
            import asyncio
            asyncio.create_task(self.agent_runtime.execute_session(session_id))
            logger.info(f"Spawned coding session {session_id} to fix repeated failure.")
            return True
        except Exception as e:
            logger.error(f"Error spawning agent session: {e}")
            return False

    async def _apply_semantic_overlap(self, proposal: ImprovementProposal) -> bool:
        """Consolidate the overlapping memories."""
        mem_id_1 = proposal.metadata.get("memory_id_1")
        mem_id_2 = proposal.metadata.get("memory_id_2")
        consolidated = proposal.metadata.get("consolidated_content")

        if not mem_id_1 or not mem_id_2 or not consolidated:
            logger.error("Missing memory IDs or consolidated content in proposal metadata.")
            return False

        # 1. Delete both old memories
        await self.memory_manager.delete(mem_id_1, force=True)
        await self.memory_manager.delete(mem_id_2, force=True)

        # 2. Store the new consolidated memory
        await self.memory_manager.store(
            type="semantic",
            content=consolidated,
            tier="permanent",
            importance=0.8,
            is_protected=False,
            category="consolidated_overlap"
        )
        logger.info(f"Consolidated memories {mem_id_1} and {mem_id_2} into a single entry.")
        return True

    async def _apply_prompt_drift(self, proposal: ImprovementProposal) -> bool:
        """Update the prompt registry template."""
        if not self.prompt_registry:
            logger.error("PromptRegistry not configured in ReviewGate.")
            return False

        prompt_name = proposal.metadata.get("target_prompt_name")
        new_template = proposal.metadata.get("optimized_template")

        if not prompt_name or not new_template:
            logger.error("Missing prompt name or optimized template in metadata.")
            return False

        # Register a new version
        now_version = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        self.prompt_registry.register(
            name=prompt_name,
            version=f"evo_{now_version}",
            template=new_template,
            set_active=True
        )
        logger.info(f"Updated prompt '{prompt_name}' to version 'evo_{now_version}'.")
        return True

    async def _apply_missing_package(self, proposal: ImprovementProposal) -> bool:
        """Install package and update manifests."""
        pkg = proposal.metadata.get("package_name")
        sys_type = proposal.metadata.get("system")
        cmd = proposal.metadata.get("install_command") or proposal.recommended_solution

        if not pkg or not sys_type:
            logger.error("Missing package_name or system in proposal metadata.")
            return False

        logger.info(f"Executing dependency installation: {cmd}")
        # Execute the shell command safely
        try:
            # We run the command via subprocess
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60, creationflags=CREATION_FLAGS)
            if res.returncode != 0:
                logger.error(f"Installation command failed: {res.stderr}")
                return False
        except Exception as e:
            logger.error(f"Installation failed: {e}")
            return False

        # Update dependency manifests (e.g. requirements.txt or package.json)
        if sys_type == "python" and os.path.exists("requirements.txt"):
            try:
                with open("requirements.txt", "a+", encoding="utf-8") as f:
                    f.seek(0)
                    content = f.read()
                    if pkg not in content:
                        f.write(f"\n{pkg}\n")
                        logger.info(f"Added {pkg} to requirements.txt")
            except Exception as e:
                logger.error(f"Failed to update requirements.txt: {e}")
        elif sys_type == "node" and os.path.exists("package.json"):
            try:
                with open("package.json", "r+", encoding="utf-8") as f:
                    data = json.load(f)
                    if "dependencies" not in data:
                        data["dependencies"] = {}
                    data["dependencies"][pkg] = "latest"
                    f.seek(0)
                    json.dump(data, f, indent=2)
                    f.truncate()
                    logger.info(f"Added {pkg} to package.json dependencies")
            except Exception as e:
                logger.error(f"Failed to update package.json: {e}")

        return True

    async def _get_proposal(self, proposal_id: str) -> Optional[ImprovementProposal]:
        query = "SELECT * FROM evolution_proposals WHERE id = ?"
        try:
            with self.db_pool.get_read_connection() as conn:
                row = conn.execute(query, (proposal_id,)).fetchone()
                if row:
                    return ImprovementProposal.from_row(row)
        except Exception as e:
            logger.error(f"Error fetching proposal {proposal_id}: {e}")
        return None

    async def _update_status(self, proposal_id: str, status: str):
        query = "UPDATE evolution_proposals SET status = ? WHERE id = ?"
        try:
            with self.db_pool.get_write_connection() as conn:
                conn.execute(query, (status, proposal_id))
        except Exception as e:
            logger.error(f"Error updating status of proposal {proposal_id}: {e}")
