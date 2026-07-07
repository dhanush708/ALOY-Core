import time
from typing import Dict, Any, Optional
from agent.types import RuntimeMetrics


class RuntimeMetricsCollector:
    """Gathers and exposes runtime metrics for agent sessions."""

    def __init__(self):
        self._active_sessions: Dict[str, Dict[str, Any]] = {}

    def start_session(self, session_id: str) -> None:
        """Start tracking metrics for a new session."""
        self._active_sessions[session_id] = {
            "start_time": time.perf_counter(),
            "model_usage": {},
            "token_usage": {"input": 0, "output": 0},
            "tool_calls": {},
            "reasoning_depths": [],
            "latency_ms": {},
        }

    def record_tool_call(self, session_id: str, tool_name: str) -> None:
        """Increment count for a tool call."""
        if session_id in self._active_sessions:
            calls = self._active_sessions[session_id]["tool_calls"]
            calls[tool_name] = calls.get(tool_name, 0) + 1

    def record_model_call(
        self,
        session_id: str,
        model_name: str,
        latency_ms: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """Record model routing call statistics."""
        if session_id in self._active_sessions:
            sess = self._active_sessions[session_id]
            # Model usage count
            sess["model_usage"][model_name] = sess["model_usage"].get(model_name, 0) + 1
            # Token usage
            sess["token_usage"]["input"] += input_tokens
            sess["token_usage"]["output"] += output_tokens
            # Latency tracking
            if model_name not in sess["latency_ms"]:
                sess["latency_ms"][model_name] = 0.0
            sess["latency_ms"][model_name] += latency_ms

    def record_reasoning_depth(self, session_id: str, depth: int) -> None:
        """Record maximum reasoning search depth reached."""
        if session_id in self._active_sessions:
            self._active_sessions[session_id]["reasoning_depths"].append(depth)

    def end_session(self, session_id: str) -> Optional[RuntimeMetrics]:
        """Finalize tracking and return the collected RuntimeMetrics."""
        if session_id not in self._active_sessions:
            return None

        sess = self._active_sessions.pop(session_id)
        duration = time.perf_counter() - sess["start_time"]

        max_depth = max(sess["reasoning_depths"]) if sess["reasoning_depths"] else 0

        return RuntimeMetrics(
            duration_seconds=duration,
            latency_ms=sess["latency_ms"],
            model_usage=sess["model_usage"],
            token_usage=sess["token_usage"],
            tool_calls=sess["tool_calls"],
            reasoning_depth=max_depth,
        )

    def get_metrics(self, session_id: str) -> Optional[RuntimeMetrics]:
        """Get current metrics for a session without ending it."""
        if session_id not in self._active_sessions:
            return None
        sess = self._active_sessions[session_id]
        duration = time.perf_counter() - sess["start_time"]
        max_depth = max(sess["reasoning_depths"]) if sess["reasoning_depths"] else 0
        return RuntimeMetrics(
            duration_seconds=duration,
            latency_ms=sess["latency_ms"].copy(),
            model_usage=sess["model_usage"].copy(),
            token_usage=sess["token_usage"].copy(),
            tool_calls=sess["tool_calls"].copy(),
            reasoning_depth=max_depth,
        )
