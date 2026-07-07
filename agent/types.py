import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional, Callable


class AgentSessionState(str, Enum):
    PLANNING = "planning"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class TaskStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskStep:
    id: str
    session_id: str
    assigned_agent: str
    title: str
    description: str
    parent_task_id: Optional[str] = None
    priority: int = 5  # 1=critical, 10=low
    status: TaskStatus = TaskStatus.PENDING
    retry_count: int = 0
    max_retries: int = 3
    depends_on: List[str] = field(default_factory=list)  # task IDs that must complete first
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionContext:
    session_id: str
    project_id: str
    goal: str
    workspace_path: str
    manifest: Dict[str, Any] = field(default_factory=dict)
    current_task: Optional[TaskStep] = None
    conversation_context: Optional[Dict[str, Any]] = None
    memory_context: Optional[Dict[str, Any]] = None
    knowledge_context: Optional[Dict[str, Any]] = None
    reasoning_context: Optional[Dict[str, Any]] = None
    model_context: Dict[str, Any] = field(default_factory=dict)
    allowed_tools: List[str] = field(default_factory=list)
    allowed_paths: List[str] = field(default_factory=list)
    user_permissions: List[str] = field(default_factory=list)
    cancellation_token: asyncio.Event = field(default_factory=asyncio.Event)
    progress_reporter: Optional[Callable[[str, Dict[str, Any]], Any]] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentModelAffinity:
    agent_name: str
    preferred_model: str
    fallback_model: Optional[str] = None


@dataclass
class SelfEvaluationResult:
    task_id: str
    success: bool
    score: float  # 0.0 to 1.0
    summary: str
    lessons_learned: List[str] = field(default_factory=list)
    errors_encountered: List[str] = field(default_factory=list)
    fixes_applied: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RuntimeMetrics:
    duration_seconds: float = 0.0
    latency_ms: Dict[str, float] = field(default_factory=dict)
    model_usage: Dict[str, int] = field(default_factory=dict)  # model -> call_count
    token_usage: Dict[str, int] = field(default_factory=dict)  # input/output -> tokens
    tool_calls: Dict[str, int] = field(default_factory=dict)  # tool_name -> count
    reasoning_depth: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionJournal:
    session_id: str
    goal: str
    plan_steps: List[Dict[str, Any]] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)
    tests_executed: List[Dict[str, Any]] = field(default_factory=list)
    errors_encountered: List[str] = field(default_factory=list)
    fixes_applied: List[str] = field(default_factory=list)
    lessons_learned: List[str] = field(default_factory=list)
    models_used: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    final_outcome: str = "failed"  # completed | failed | rolled_back
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskResult:
    success: bool
    result: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
