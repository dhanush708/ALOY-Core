import uuid
import json
import logging
import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

from kernel.interfaces.base import HealthStatus
from kernel.interfaces.reasoning import IReasoningEngine
from kernel.prompts import PromptRegistry
from kernel.types import Event
from models.router import ModelRouter
from database.connection import DatabaseConnectionPool

from .templates import detect_strategy_and_template
from .strategies import ReasoningStrategies
from .verifier import SelfVerifier, VerificationResult

logger = logging.getLogger(__name__)

class ReasoningEngine(IReasoningEngine):
    """Reasoning Engine subsystem implementation."""
    
    def __init__(
        self,
        model_router: ModelRouter,
        prompt_registry: PromptRegistry,
        event_bus=None,
        db_pool: Optional[DatabaseConnectionPool] = None
    ):
        self.model_router = model_router
        self.prompt_registry = prompt_registry
        self.event_bus = event_bus
        self.db_pool = db_pool
        
        self.strategies = ReasoningStrategies(model_router, prompt_registry, self._publish_stage_event)
        self.verifier = SelfVerifier(model_router, prompt_registry)
        
        # Subsystem metrics
        self._execution_count = 0
        self._error_count = 0
        self._total_duration_ms = 0.0
        self._started = False
        
    async def start(self) -> None:
        """Initialize the subsystem."""
        self._started = True
        logger.info("Reasoning Engine started.")
        # Perform initial cleanup of expired temporary logs
        self._cleanup_expired_logs()
        
    async def stop(self) -> None:
        """Shut down the subsystem."""
        self._started = False
        logger.info("Reasoning Engine stopped.")
        
    async def health_check(self) -> HealthStatus:
        """Check subsystem health."""
        if not self._started:
            return HealthStatus.UNHEALTHY
        try:
            # Check if model router is healthy and registry is accessible
            if self.model_router is not None and self.prompt_registry is not None:
                return HealthStatus.HEALTHY
            return HealthStatus.DEGRADED
        except Exception:
            return HealthStatus.UNHEALTHY
            
    def get_metrics(self) -> Dict[str, Any]:
        """Expose current runtime metrics."""
        return {
            "execution_count": self._execution_count,
            "error_count": self._error_count,
            "avg_duration_ms": (
                self._total_duration_ms / self._execution_count
                if self._execution_count > 0 else 0.0
            ),
            "started": self._started
        }
        
    async def _publish_stage_event(self, phase: str, stage_name: str, data: Dict[str, Any]):
        """Helper to publish intermediate reasoning stage events to the Event Bus."""
        if not self.event_bus:
            return
            
        event_type = (
            "reasoning.stage.started" if phase == "started"
            else "reasoning.stage.completed"
        )
        
        event = Event(
            type=event_type,
            data={
                "stage": stage_name,
                **data
            },
            source="reasoning_engine"
        )
        await self.event_bus.publish(event)

    async def reason(
        self,
        query: str,
        context: Dict[str, Any],
        depth: str = "medium"
    ) -> Dict[str, Any]:
        """Perform reasoning using specified strategies and depths."""
        start_time = time.perf_counter()
        self._execution_count += 1
        correlation_id = context.get("correlation_id", str(uuid.uuid4()))
        
        # Publish start event
        if self.event_bus:
            await self.event_bus.publish(Event(
                type="reasoning.started",
                data={
                    "query": query,
                    "depth": depth,
                    "strategy": context.get("strategy"),
                    "session_id": context.get("session_id")
                },
                source="reasoning_engine",
                correlation_id=correlation_id
            ))
            
        try:
            # 1. Resolve strategy & planning template
            strategy = context.get("strategy")
            template_name = context.get("template")
            
            if not strategy:
                strategy, resolved_template = detect_strategy_and_template(query, context)
                if not template_name:
                    template_name = resolved_template
                    
            logger.info(f"Executing reasoning strategy: {strategy} at depth: {depth}")
            
            # 2. Check for temporary log reuse (Reasoning Memory)
            cached_result = self._check_and_increment_reuse(query)
            if cached_result:
                # Return cached result directly
                duration = (time.perf_counter() - start_time) * 1000
                self._total_duration_ms += duration
                
                if self.event_bus:
                    await self.event_bus.publish(Event(
                        type="reasoning.completed",
                        data={
                            "final_output": cached_result["final_output"],
                            "duration_ms": duration,
                            "cached": True
                        },
                        source="reasoning_engine",
                        correlation_id=correlation_id
                    ))
                return cached_result

            # 3. Dispatch to strategy handler
            result = None
            if strategy == "direct_answer":
                result = await self.strategies.direct_answer(query, context, depth)
            elif strategy == "chain_of_thought":
                result = await self.strategies.chain_of_thought(query, context, depth, template_name)
            elif strategy == "deep_reasoning":
                result = await self.strategies.deep_reasoning(query, context, depth)
            elif strategy == "tree_of_thought":
                result = await self.strategies.tree_of_thought(query, context, depth)
            elif strategy == "debate":
                result = await self.strategies.debate(query, context, depth)
            elif strategy == "planning":
                result = await self.strategies.planning(query, context, depth)
            elif strategy == "verification":
                result = await self.strategies.verification(query, context, depth)
            elif strategy == "reflection":
                result = await self.strategies.reflection(query, context, depth)
            else:
                # Fallback to chain_of_thought
                result = await self.strategies.chain_of_thought(query, context, depth, "exploratory_analysis")
                strategy = "chain_of_thought"
                
            final_output = result["final_output"]
            thought = result["thought"]
            steps = result["steps"]
            duration = result["duration_ms"]
            
            # 4. Self-Verification and Correction Loop (Optional & Modular)
            verification_result = None
            max_corrections = 2
            correction_count = 0
            
            while correction_count <= max_corrections:
                if context.get("verify", True):
                    verification_result = await self.verifier.verify(query, final_output, steps, context)
                    
                    if verification_result.is_valid:
                        logger.info("Reasoning output verified as valid (is_valid=True).")
                        break
                        
                    # If invalid and we haven't exhausted correction passes, run a correction step
                    if correction_count < max_corrections:
                        logger.warning(
                            "Verification failed (confidence=%s, contradictions=%d, risk=%s). Running correction pass %d/%d...",
                            verification_result.confidence_score,
                            len(verification_result.logical_contradictions),
                            verification_result.hallucination_risk,
                            correction_count + 1,
                            max_corrections
                        )
                        
                        try:
                            # Load correction prompt
                            try:
                                correct_template = self.prompt_registry.get("reasoning.correct")
                                correct_prompt = correct_template.render(
                                    query=query,
                                    output=final_output,
                                    contradictions=", ".join(verification_result.logical_contradictions) or "None",
                                    assumptions=", ".join(verification_result.missing_assumptions) or "None",
                                    incomplete=", ".join(verification_result.incomplete_reasoning) or "None"
                                )
                            except Exception as e:
                                logger.warning(f"Could not load correction prompt from registry: {e}. Using fallback.")
                                correct_prompt = (
                                    f"Refine the answer for query: '{query}'.\n"
                                    f"Current output: {final_output}\n"
                                    f"Contradictions to resolve: {verification_result.logical_contradictions}\n"
                                    f"Missing assumptions: {verification_result.missing_assumptions}\n"
                                    "Provide a corrected, logical, and mathematically consistent response."
                                )
                            
                            # Generate refined output using heavy model (reasoning_request)
                            refined_response = await self.model_router.generate(
                                task="reasoning_request",
                                prompt=correct_prompt,
                                options={"temperature": 0.0}
                            )
                            
                            # Append a step for correction
                            steps.append({
                                "stage": f"Correction Pass {correction_count + 1}",
                                "content": f"Resolved contradictions: {', '.join(verification_result.logical_contradictions or ['None'])}"
                            })
                            
                            final_output = refined_response
                            correction_count += 1
                        except Exception as corr_err:
                            logger.error(f"Correction pass failed: {corr_err}")
                            break
                    else:
                        # Exhausted correction passes
                        logger.warning("Exhausted correction passes. Proceeding with last generated output.")
                        break
                else:
                    break
                    
            confidence = verification_result.confidence_score if verification_result else 1.0
            
            # 5. Save reasoning log to database (Reasoning Memory)
            log_id = str(uuid.uuid4())
            self._save_log(log_id, query, strategy, depth, steps, final_output, confidence)
            
            # Compile final response dictionary
            response_dict = {
                "id": log_id,
                "final_output": final_output,
                "thought": thought,
                "steps": steps,
                "duration_ms": duration,
                "strategy": strategy,
                "depth": depth,
                "verification": {
                    "is_valid": verification_result.is_valid if verification_result else True,
                    "confidence_score": confidence,
                    "logical_contradictions": verification_result.logical_contradictions if verification_result else [],
                    "missing_assumptions": verification_result.missing_assumptions if verification_result else [],
                    "hallucination_risk": verification_result.hallucination_risk if verification_result else 0.0,
                    "incomplete_reasoning": verification_result.incomplete_reasoning if verification_result else [],
                    "recommendations": verification_result.recommendations if verification_result else []
                } if verification_result else None
            }
            
            # 6. Publish completion event
            total_duration = (time.perf_counter() - start_time) * 1000
            self._total_duration_ms += total_duration
            
            if self.event_bus:
                await self.event_bus.publish(Event(
                    type="reasoning.completed",
                    data={
                        "id": log_id,
                        "final_output": final_output,
                        "duration_ms": total_duration,
                        "strategy": strategy,
                        "depth": depth,
                        "confidence": confidence
                    },
                    source="reasoning_engine",
                    correlation_id=correlation_id
                ))
                
            return response_dict
            
        except Exception as e:
            self._error_count += 1
            logger.error(f"Reasoning process failed: {e}", exc_info=True)
            
            if self.event_bus:
                await self.event_bus.publish(Event(
                    type="reasoning.failed",
                    data={
                        "query": query,
                        "error": str(e)
                    },
                    source="reasoning_engine",
                    correlation_id=correlation_id
                ))
            raise e
            
    def _save_log(
        self,
        log_id: str,
        query: str,
        strategy: str,
        depth: str,
        steps: List[Dict[str, Any]],
        final_output: str,
        confidence: Optional[float]
    ) -> None:
        """Persist a temporary log of the reasoning session."""
        if not self.db_pool:
            return
        try:
            created_at = datetime.now(timezone.utc).isoformat()
            expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
            
            with self.db_pool.get_write_connection() as conn:
                conn.execute("""
                    INSERT INTO reasoning_logs (id, query, strategy, depth, steps, final_output, confidence, use_count, created_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """, (
                    log_id,
                    query,
                    strategy,
                    depth,
                    json.dumps(steps),
                    final_output,
                    confidence,
                    created_at,
                    expires_at
                ))
        except Exception as e:
            logger.error(f"Failed to save reasoning log: {e}")

    def _check_and_increment_reuse(self, query: str) -> Optional[Dict[str, Any]]:
        """Verify if reasoning for query already exists, increment use count, and handle promotion."""
        if not self.db_pool:
            return None
        try:
            with self.db_pool.get_write_connection() as conn:
                row = conn.execute(
                    "SELECT * FROM reasoning_logs WHERE query = ? LIMIT 1",
                    (query,)
                ).fetchone()
                
                if row:
                    new_count = row["use_count"] + 1
                    conn.execute(
                        "UPDATE reasoning_logs SET use_count = ? WHERE id = ?",
                        (new_count, row["id"])
                    )
                    
                    steps = json.loads(row["steps"])
                    
                    # Distillation and promotion threshold (e.g. 3 accesses)
                    if new_count >= 3:
                        self._trigger_promotion(row)
                        
                    return {
                        "id": row["id"],
                        "final_output": row["final_output"],
                        "thought": f"Re-used reasoning path (use_count={new_count}).",
                        "steps": steps,
                        "duration_ms": 0.0, # instant
                        "strategy": row["strategy"],
                        "depth": row["depth"],
                        "promoted": new_count >= 3
                    }
        except Exception as e:
            logger.error(f"Failed to check/increment reasoning log reuse: {e}")
        return None

    def _trigger_promotion(self, log_row) -> None:
        """Publish promotion event requesting Learning Engine to distill patterns into procedural memory."""
        if not self.event_bus:
            return
            
        event = Event(
            type="memory.promoted",
            data={
                "source": "reasoning_engine",
                "original_log_id": log_row["id"],
                "query": log_row["query"],
                "final_output": log_row["final_output"],
                "steps": json.loads(log_row["steps"]),
                "strategy": log_row["strategy"],
                "depth": log_row["depth"]
            },
            source="reasoning_engine"
        )
        # Fire-and-forget publish
        asyncio.create_task(self.event_bus.publish(event))
        logger.info(f"Reasoning log {log_row['id']} designated for promotion due to high reuse.")

    def _cleanup_expired_logs(self) -> None:
        """Perform database purge of expired temporary reasoning logs."""
        if not self.db_pool:
            return
        try:
            now = datetime.now(timezone.utc).isoformat()
            with self.db_pool.get_write_connection() as conn:
                cursor = conn.execute("DELETE FROM reasoning_logs WHERE expires_at < ?", (now,))
                deleted = cursor.rowcount
                if deleted > 0:
                    logger.info(f"Cleaned up {deleted} expired temporary reasoning logs.")
        except Exception as e:
            logger.error(f"Failed to clean up expired reasoning logs: {e}")
