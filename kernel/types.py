from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any
import uuid

@dataclass
class Event:
    """Enhanced event class representing something that happened in the system."""
    type: str
    data: Dict[str, Any]
    source: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    priority: int = 0  # 0=normal, 1=high, 2=critical
    ttl_seconds: int = 300
    retry_count: int = 0
    max_retries: int = 3

    def is_expired(self) -> bool:
        """Check if the event has expired based on TTL."""
        now = datetime.now(timezone.utc)
        elapsed = (now - self.timestamp).total_seconds()
        return elapsed > self.ttl_seconds

# Standard event types
SYSTEM_BOOT_COMPLETED = "system.boot.completed"
SYSTEM_SHUTDOWN_INITIATED = "system.shutdown.initiated"
SYSTEM_HEALTH_DEGRADED = "system.health.degraded"
SYSTEM_BACKUP_COMPLETED = "system.backup.completed"

CONVERSATION_STARTED = "conversation.started"
CONVERSATION_TURN_COMPLETED = "conversation.turn.completed"
CONVERSATION_TOOL_CALLED = "conversation.tool.called"
CONVERSATION_TOOL_RESULT = "conversation.tool.result"
CONVERSATION_ERROR = "conversation.error"

MEMORY_CREATED = "memory.created"
MEMORY_UPDATED = "memory.updated"
MEMORY_ACCESSED = "memory.accessed"
MEMORY_PROMOTED = "memory.promoted"
MEMORY_ARCHIVED = "memory.archived"
MEMORY_MERGED = "memory.merged"
MEMORY_CONFLICT = "memory.conflict"

LEARNING_TASK_QUEUED = "learning.task.queued"
LEARNING_TASK_COMPLETED = "learning.task.completed"
LEARNING_TASK_FAILED = "learning.task.failed"
LEARNING_FEEDBACK_RECEIVED = "learning.feedback.received"

AGENT_SESSION_STARTED = "agent.session.started"
AGENT_STATE_CHANGED = "agent.state.changed"
AGENT_PLAN_GENERATED = "agent.plan.generated"
AGENT_PLAN_APPROVED = "agent.plan.approved"
AGENT_STEP_STARTED = "agent.step.started"
AGENT_STEP_COMPLETED = "agent.step.completed"
AGENT_STEP_FAILED = "agent.step.failed"
AGENT_CHECKPOINT_SAVED = "agent.checkpoint.saved"

MODEL_PRELOAD_REQUESTED = "model.preload.requested"
MODEL_SWITCHED = "model.switched"
MODEL_ERROR = "model.error"

SECURITY_ACTION_REQUESTED = "security.action.requested"
SECURITY_ACTION_APPROVED = "security.action.approved"
SECURITY_VIOLATION = "security.violation"
SECURITY_APPROVAL_TIMEOUT = "security.approval.timeout"

# Legacy (kept for backward compat with existing subscribers)
TOOL_EXECUTED = "tool.executed"

# Mission 7 — Tool System event types
TOOL_STARTED = "tool.started"
TOOL_PROGRESS = "tool.progress"
TOOL_COMPLETED = "tool.completed"
TOOL_FAILED = "tool.failed"
TOOL_CANCELLED = "tool.cancelled"

# Mission 5 — Reasoning Engine event types
REASONING_STARTED = "reasoning.started"
REASONING_STAGE_STARTED = "reasoning.stage.started"
REASONING_STAGE_COMPLETED = "reasoning.stage.completed"
REASONING_COMPLETED = "reasoning.completed"
REASONING_FAILED = "reasoning.failed"


# Mission 11 — Agent Runtime additional events
AGENT_SESSION_COMPLETED   = "agent.session.completed"
AGENT_SESSION_FAILED      = "agent.session.failed"
AGENT_SESSION_PAUSED      = "agent.session.paused"
AGENT_SESSION_RESUMED     = "agent.session.resumed"
AGENT_SESSION_ROLLED_BACK = "agent.session.rolled_back"

TASK_CREATED   = "agent.task.created"
TASK_STARTED   = "agent.task.started"
TASK_COMPLETED = "agent.task.completed"
TASK_FAILED    = "agent.task.failed"
TASK_RETRY     = "agent.task.retry"
TASK_CANCELLED = "agent.task.cancelled"

CHECKPOINT_CREATED    = "agent.checkpoint.created"
ROLLBACK_STARTED      = "agent.rollback.started"
ROLLBACK_COMPLETED    = "agent.rollback.completed"

WORKSPACE_LOCKED   = "workspace.locked"
WORKSPACE_UNLOCKED = "workspace.unlocked"

