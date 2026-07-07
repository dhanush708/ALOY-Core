import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from database.connection import DatabaseConnectionPool
from agent.types import ExecutionJournal, TaskStatus, AgentSessionState
from agent.metrics import RuntimeMetricsCollector

logger = logging.getLogger(__name__)


class ExecutionJournalWriter:
    """Auto-generates structured execution journals upon agent session completion."""

    def __init__(self, db_pool: DatabaseConnectionPool, metrics_collector: RuntimeMetricsCollector):
        self.db_pool = db_pool
        self.metrics = metrics_collector

    def _get_journals_dir(self, workspace_path: str) -> Path:
        path = Path(workspace_path) / ".aloy" / "journals"
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def generate_journal(self, session_id: str, workspace_path: str) -> Optional[ExecutionJournal]:
        """Loads execution details from DB and metrics to compile a complete session journal."""
        logger.info("Generating execution journal for session: %s", session_id)

        # 1. Fetch Session details
        with self.db_pool.get_read_connection() as conn:
            session_row = conn.execute(
                "SELECT goal, status, created_at FROM agent_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()

        if not session_row:
            logger.warning("Session %s not found in DB.", session_id)
            return None

        goal, status, created_at_str = session_row

        # 2. Fetch Tasks
        with self.db_pool.get_read_connection() as conn:
            task_rows = conn.execute(
                """
                SELECT id, assigned_agent, title, description, status, result, error, metadata 
                FROM agent_tasks WHERE session_id = ?
                """,
                (session_id,),
            ).fetchall()

        plan_steps = []
        files_modified = set()
        tests_executed = []
        errors_encountered = []
        fixes_applied = []
        lessons_learned = []

        for row in task_rows:
            t_id, agent, title, desc, t_status, result, error, meta_str = row
            meta = json.loads(meta_str) if meta_str else {}

            plan_steps.append({
                "id": t_id,
                "agent": agent,
                "title": title,
                "status": t_status,
            })

            # Track files modified
            if agent == "coder" and meta.get("modified_files"):
                for f in meta["modified_files"]:
                    files_modified.add(f)

            # Track tests
            if agent == "tester":
                tests_executed.append({
                    "task_title": title,
                    "passed": t_status == TaskStatus.DONE,
                    "details": result or error,
                })

            # Track errors & fixes
            if t_status == TaskStatus.FAILED:
                errors_encountered.append(error or "Unknown task failure")
            elif agent == "debugger" and t_status == TaskStatus.DONE:
                fixes_applied.append(result or "Bug fixed")

            # Extract lessons from learning agent result
            if agent == "learner" and t_status == TaskStatus.DONE:
                lessons_learned.append(result or "No lesson notes extracted")

        # 3. Pull metrics
        sess_metrics = self.metrics.end_session(session_id)
        metrics_dict = {}
        duration = 0.0
        models_used = []

        if sess_metrics:
            metrics_dict = {
                "duration_seconds": sess_metrics.duration_seconds,
                "model_usage": sess_metrics.model_usage,
                "token_usage": sess_metrics.token_usage,
                "tool_calls": sess_metrics.tool_calls,
                "reasoning_depth": sess_metrics.reasoning_depth,
            }
            duration = sess_metrics.duration_seconds
            models_used = list(sess_metrics.model_usage.keys())

        # Compile Journal
        journal = ExecutionJournal(
            session_id=session_id,
            goal=goal,
            plan_steps=plan_steps,
            files_modified=list(files_modified),
            tests_executed=tests_executed,
            errors_encountered=errors_encountered,
            fixes_applied=fixes_applied,
            lessons_learned=lessons_learned,
            models_used=models_used,
            duration_seconds=duration,
            final_outcome=status,
            metrics=metrics_dict,
        )

        # 4. Save to disk in workspace's .aloy/journals directory
        journals_dir = self._get_journals_dir(workspace_path)
        journal_file = journals_dir / f"journal_{session_id}.json"
        
        with open(journal_file, "w", encoding="utf-8") as f:
            json.dump(journal.__dict__, f, indent=2)

        # Also write a human-readable markdown version
        md_file = journals_dir / f"journal_{session_id}.md"
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(self.to_markdown(journal))

        logger.info("Journal files written successfully.")
        return journal

    def to_markdown(self, journal: ExecutionJournal) -> str:
        """Helper to generate a beautiful markdown string representing the journal."""
        steps_md = "\n".join(
            f"- [{ 'x' if s['status'] == 'done' else ' ' }] **{s['agent']}**: {s['title']} ({s['status']})"
            for s in journal.plan_steps
        )
        files_md = "\n".join(f"- `{f}`" for f in journal.files_modified) or "*None*"
        errors_md = "\n".join(f"- {e}" for e in journal.errors_encountered) or "*None*"
        fixes_md = "\n".join(f"- {f}" for f in journal.fixes_applied) or "*None*"
        lessons_md = "\n".join(f"- {l}" for l in journal.lessons_learned) or "*None*"
        models_md = ", ".join(f"`{m}`" for m in journal.models_used) or "*None*"

        return f"""# Execution Journal — Session {journal.session_id}

## Overview
- **Goal**: {journal.goal}
- **Final Outcome**: **{journal.final_outcome.upper()}**
- **Duration**: {journal.duration_seconds:.2f} seconds
- **Models Used**: {models_md}

## Plan Steps Execution
{steps_md}

## Files Modified
{files_md}

## Errors Encountered
{errors_md}

## Fixes Applied
{fixes_md}

## Lessons Learned
{lessons_md}

## Metrics Detail
```json
{json.dumps(journal.metrics, indent=2)}
```
"""
