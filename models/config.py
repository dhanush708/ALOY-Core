"""Centralized Model Configuration for ALOY Subsystems.

All subsystems (health checks, router, startup validation, settings, installer)
read from this single configuration. Changing a model name here updates the
entire application automatically.
"""

MODELS_CONFIG = {
    "chat": {
        "required": True,
        "name": "qwen3:14b",
        "label": "Primary Chat Model",
        "size_gb": 9.0,
        "description": "Used for standard conversation, classification, planning, and agent tasks.",
    },
    "coding": {
        "required": True,
        "name": "qwen2.5-coder:14b",
        "label": "Primary Coding Model",
        "size_gb": 9.0,
        "description": "Used for code generation, workspace indexing, and FSM agent tasks.",
    },
    "embedding": {
        "required": False,
        "name": "nomic-embed-text:latest",
        "label": "Vector Embeddings Model",
        "size_gb": 0.5,
        "description": "Provides semantic vector search capabilities. (Falls back to FTS5 search if missing).",
    },
    "reasoning": {
        "required": False,
        "name": "deepseek-r1:14b",
        "label": "Deep Reasoning Model",
        "size_gb": 9.0,
        "description": "Enables multi-stage tree-of-thought verification and deep reasoning features.",
    },
    "vision": {
        "required": False,
        "name": "phi4-mini:latest",
        "label": "Lite / Vision Model",
        "size_gb": 4.3,
        "description": "Lightweight model for fast responses and image input processing.",
    },
}
