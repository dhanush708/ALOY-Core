"""
Runtime latency and health tracking for models.
"""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ModelHealth:
    """Snapshot of a model's runtime health."""
    model: str
    avg_latency_ms: float
    p95_latency_ms: float
    total_calls: int
    error_count: int
    error_rate: float          # 0.0 – 1.0
    status: str                # 'healthy', 'degraded', 'unhealthy'


class ModelTracker:
    """Records per-model, per-task latency and error metrics."""

    ERROR_RATE_DEGRADED = 0.10   # ≥10 % → degraded
    ERROR_RATE_UNHEALTHY = 0.30  # ≥30 % → unhealthy
    MAX_HISTORY = 200            # keep last N samples per (model, task)

    def __init__(self):
        # key: (model, task) → list of latency_ms floats
        self._latencies: Dict[tuple, List[float]] = defaultdict(list)
        # key: (model, task) → count of errors
        self._errors: Dict[tuple, int] = defaultdict(int)
        # key: (model, task) → total calls
        self._calls: Dict[tuple, int] = defaultdict(int)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------
    def record_success(self, model: str, task: str, latency_ms: float) -> None:
        key = (model, task)
        self._calls[key] += 1
        self._latencies[key].append(latency_ms)
        if len(self._latencies[key]) > self.MAX_HISTORY:
            self._latencies[key] = self._latencies[key][-self.MAX_HISTORY:]

    def record_error(self, model: str, task: str) -> None:
        key = (model, task)
        self._calls[key] += 1
        self._errors[key] += 1

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------
    def get_health(self, model: str) -> ModelHealth:
        """Aggregate health across all tasks for *model*."""
        all_latencies: List[float] = []
        total_calls = 0
        total_errors = 0

        for (m, _task), lats in self._latencies.items():
            if m == model:
                all_latencies.extend(lats)
        for (m, _task), cnt in self._calls.items():
            if m == model:
                total_calls += cnt
        for (m, _task), err in self._errors.items():
            if m == model:
                total_errors += err

        avg = sum(all_latencies) / len(all_latencies) if all_latencies else 0.0
        sorted_lats = sorted(all_latencies)
        p95 = sorted_lats[int(len(sorted_lats) * 0.95)] if sorted_lats else 0.0
        error_rate = total_errors / total_calls if total_calls else 0.0

        if error_rate >= self.ERROR_RATE_UNHEALTHY:
            status = "unhealthy"
        elif error_rate >= self.ERROR_RATE_DEGRADED:
            status = "degraded"
        else:
            status = "healthy"

        return ModelHealth(
            model=model,
            avg_latency_ms=avg,
            p95_latency_ms=p95,
            total_calls=total_calls,
            error_count=total_errors,
            error_rate=error_rate,
            status=status,
        )

    def is_degraded(self, model: str) -> bool:
        return self.get_health(model).status in ("degraded", "unhealthy")
