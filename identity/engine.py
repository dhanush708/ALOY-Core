import logging
import json
from pathlib import Path
from typing import Dict, Any, Optional
from identity.profile import CREATOR_PROFILE_CONTENT, ALOY_IDENTITY_CONTENT

logger = logging.getLogger(__name__)

class IdentityEngine:
    """Manages ALOY's identity, founder details, capabilities, and workspace context."""

    def __init__(self, db_pool, memory_manager):
        self.db_pool = db_pool
        self.memory_manager = memory_manager

    async def initialize_if_needed(self):
        """Seed creator and identity profiles into memories table if not already present."""
        # 1. Seed Creator Profile
        creator_exists = await self._profile_exists("creator_profile")
        if not creator_exists:
            logger.info("Seeding creator profile memory...")
            await self.memory_manager.store(
                type="creator_profile",
                content=CREATOR_PROFILE_CONTENT,
                tier="long_term",
                importance=1.0,
                is_protected=True,
                metadata={"memory_class": "creator_memory"}
            )
        else:
            logger.info("Creator profile memory already exists.")

        # Delete legacy founder_profile if present to prevent personal info leakage
        with self.db_pool.get_write_connection() as conn:
            conn.execute("DELETE FROM memories WHERE type = 'founder_profile'")
            conn.commit()

        # 2. Seed ALOY Identity Profile
        identity_exists = await self._profile_exists("identity_profile")
        if not identity_exists:
            logger.info("Seeding ALOY identity profile memory...")
            await self.memory_manager.store(
                type="identity_profile",
                content=ALOY_IDENTITY_CONTENT,
                tier="long_term",
                importance=1.0,
                is_protected=True,
                metadata={"memory_class": "identity_memory"}
            )
        else:
            logger.info("ALOY identity profile memory already exists.")

    async def _profile_exists(self, profile_type: str) -> bool:
        with self.db_pool.get_read_connection() as conn:
            row = conn.execute("SELECT id FROM memories WHERE type = ? LIMIT 1", (profile_type,)).fetchone()
            return row is not None

    async def user_profile_exists(self) -> bool:
        """Check if user profile memory exists."""
        return await self._profile_exists("user_profile")

    async def get_user_profile(self) -> Optional[dict]:
        """Load user profile details from database metadata."""
        with self.db_pool.get_read_connection() as conn:
            row = conn.execute("SELECT metadata FROM memories WHERE type = ? LIMIT 1", ("user_profile",)).fetchone()
            if row and row["metadata"]:
                try:
                    return json.loads(row["metadata"])
                except Exception:
                    pass
        return None

    async def save_user_profile(self, name: str, preferred_name: str, age: int, country: str, preferences: str):
        """Save or update user profile memory."""
        content = f"""# User Profile
Name: {name}
Preferred Name: {preferred_name}
Age: {age}
Country: {country}

Preferences & Instructions:
{preferences}
"""
        metadata_dict = {
            "name": name,
            "preferred_name": preferred_name,
            "age": age,
            "country": country,
            "preferences": preferences
        }
        metadata_str = json.dumps(metadata_dict)

        exists = await self.user_profile_exists()
        if exists:
            with self.db_pool.get_write_connection() as conn:
                conn.execute(
                    "UPDATE memories SET content = ?, metadata = ?, updated_at = datetime('now') WHERE type = ?",
                    (content, metadata_str, "user_profile")
                )
                conn.commit()
        else:
            await self.memory_manager.store(
                type="user_profile",
                content=content,
                tier="long_term",
                importance=1.0,
                is_protected=True,
                metadata=metadata_dict
            )

    async def delete_user_profile(self):
        """Delete user profile memory from database."""
        with self.db_pool.get_write_connection() as conn:
            conn.execute("DELETE FROM memories WHERE type = ?", ("user_profile",))
            conn.commit()

    async def reset_all(self):
        """Wipe database memories/logs/sessions and trigger onboarding again."""
        with self.db_pool.get_write_connection() as conn:
            conn.execute("DELETE FROM memories")
            conn.execute("DELETE FROM conversation_messages")
            conn.execute("DELETE FROM conversations")
            conn.execute("DELETE FROM agent_tasks")
            conn.execute("DELETE FROM agent_plans")
            conn.execute("DELETE FROM agent_sessions")
            conn.execute("DELETE FROM project_sessions")
            conn.execute("DELETE FROM reasoning_logs")
            conn.execute("DELETE FROM audit_log")
            conn.commit()
        await self.initialize_if_needed()

    async def load_creator_profile(self) -> str:
        with self.db_pool.get_read_connection() as conn:
            row = conn.execute("SELECT content FROM memories WHERE type = ? LIMIT 1", ("creator_profile",)).fetchone()
            return row["content"] if row else CREATOR_PROFILE_CONTENT

    async def load_user_profile(self) -> str:
        with self.db_pool.get_read_connection() as conn:
            row = conn.execute("SELECT content FROM memories WHERE type = ? LIMIT 1", ("user_profile",)).fetchone()
            return row["content"] if row else ""

    async def load_founder_profile(self) -> str:
        """For backward compatibility, load the current user's profile."""
        user_prof = await self.load_user_profile()
        if user_prof:
            return user_prof
        return await self.load_creator_profile()

    async def load_identity_profile(self) -> str:
        with self.db_pool.get_read_connection() as conn:
            row = conn.execute("SELECT content FROM memories WHERE type = ? LIMIT 1", ("identity_profile",)).fetchone()
            return row["content"] if row else ALOY_IDENTITY_CONTENT

    def get_capability_status(self, app_state: Optional[Any] = None) -> Dict[str, bool]:
        """Dynamically check supported modules based on server app state."""
        caps = {
            "Conversation": False,
            "Memory": False,
            "Learning": False,
            "Reasoning": False,
            "Knowledge Router": False,
            "Documentation Intelligence": False,
            "Projects": False,
            "Agent Runtime": False,
            "Tool System": False,
            "Evolution": False,
            "Internet Research": False,
            "Vision": False,
            "Speech": False,
            "MCP": False,
            "Plugins": False
        }
        
        if not app_state:
            return caps
            
        caps["Conversation"] = hasattr(app_state, "engine") and app_state.engine is not None
        caps["Memory"] = hasattr(app_state, "memory_manager") and app_state.memory_manager is not None
        
        # Check if learning engine is importable / available
        try:
            from learning.engine import LearningEngine
            caps["Learning"] = True
        except ImportError:
            pass
            
        caps["Reasoning"] = hasattr(app_state, "reasoning_engine") or hasattr(app_state, "prompt_registry")
        caps["Knowledge Router"] = hasattr(app_state, "knowledge_router") and app_state.knowledge_router is not None
        caps["Documentation Intelligence"] = hasattr(app_state, "doc_intelligence") and app_state.doc_intelligence is not None
        caps["Projects"] = hasattr(app_state, "project_manager") and app_state.project_manager is not None
        caps["Agent Runtime"] = hasattr(app_state, "agent_runtime") and app_state.agent_runtime is not None
        caps["Evolution"] = hasattr(app_state, "evolution_engine") and app_state.evolution_engine is not None

        # Check tool system from agent runtime
        tool_system = None
        if hasattr(app_state, "agent_runtime") and app_state.agent_runtime:
            tool_system = getattr(app_state.agent_runtime, "tool_system", None)
        
        if tool_system:
            caps["Tool System"] = True
            metadata_list = tool_system.list_tools()
            tool_names = {meta.name for meta in metadata_list}
            caps["Internet Research"] = "web_search" in tool_names or "browser" in tool_names
            caps["Vision"] = "image_reader" in tool_names
            
        return caps

    async def get_active_workspace_info(self, project_manager) -> Optional[Dict[str, Any]]:
        """Query active projects, task counts, and git branch details directly from SQLite and git files."""
        if not project_manager:
            return None
            
        try:
            with self.db_pool.get_read_connection() as conn:
                session_row = conn.execute(
                    "SELECT project_id, id, metadata FROM project_sessions WHERE ended_at IS NULL ORDER BY started_at DESC LIMIT 1"
                ).fetchone()
                if not session_row:
                    return None
                    
                project_id = session_row["project_id"]
                session_metadata = {}
                if session_row["metadata"]:
                    try:
                        session_metadata = json.loads(session_row["metadata"])
                    except:
                        pass
                
                project_row = conn.execute(
                    "SELECT name, root_path FROM projects WHERE id = ? LIMIT 1", (project_id,)
                ).fetchone()
                if not project_row:
                    return None
                    
                project_name = project_row["name"]
                workspace_root = project_row["root_path"]
                
                # Count indexed files
                files_row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM project_files WHERE project_id = ?", (project_id,)
                ).fetchone()
                file_count = files_row["cnt"] if files_row else 0
                
                # Get active agent tasks
                task_rows = conn.execute(
                    "SELECT description FROM agent_tasks WHERE project_id = ? AND status IN ('pending', 'running') LIMIT 5",
                    (project_id,)
                ).fetchall()
                active_tasks = [t["description"] for t in task_rows]
                
                recent_files = session_metadata.get("recent_files", [])
                
                # Check git branch if HEAD exists
                git_branch = "Unknown"
                try:
                    git_dir = Path(workspace_root) / ".git"
                    if git_dir.exists():
                        head_file = git_dir / "HEAD"
                        if head_file.exists():
                            head_content = head_file.read_text().strip()
                            if head_content.startswith("ref:"):
                                git_branch = head_content.split("/")[-1]
                            else:
                                git_branch = head_content[:8]
                except Exception:
                    pass
                    
                return {
                    "project_name": project_name,
                    "workspace_root": workspace_root,
                    "file_count": file_count,
                    "active_tasks": active_tasks,
                    "recent_files": recent_files,
                    "git_branch": git_branch
                }
        except Exception as e:
            logger.warning(f"Error querying active workspace info: {e}")
            return None

    async def build_prompt_context(
        self,
        state=None,
        history=None,
        project_manager=None,
        router_engine=None,
        app_state=None
    ) -> str:
        """Assembles the identity context string directly from state and workspace context."""
        workspace_info = await self.get_active_workspace_info(project_manager)
        turn_count = getattr(state, "turn_count", 0) if state else 0
        intent = getattr(state, "current_intent", None) or "simple_chat"
        return await self.generate_identity_prompt(
            intent=intent,
            app_state=app_state,
            workspace_info=workspace_info,
            turn_count=turn_count
        )

    async def generate_identity_prompt(
        self, 
        intent: str, 
        app_state: Optional[Any] = None, 
        workspace_info: Optional[Dict[str, Any]] = None,
        turn_count: int = 0
    ) -> str:
        """Assembles the identity context string based on seeded memory and current app state."""
        creator_profile = await self.load_creator_profile()
        user_profile = await self.load_user_profile()
        identity_profile = await self.load_identity_profile()
        caps = self.get_capability_status(app_state)
        
        # Capability Text block
        caps_lines = []
        for name, supported in caps.items():
            status = "Supported (Installed and Healthy)" if supported else "Unsupported (Not Installed / Unavailable)"
            caps_lines.append(f"- {name}: {status}")
        caps_text = "\n".join(caps_lines)

        # Active Workspace / Project details
        workspace_text = "No active workspace or project session."
        if workspace_info:
            workspace_text = (
                f"- Active Project: {workspace_info.get('project_name', 'Unknown')}\n"
                f"- Active Workspace Path: {workspace_info.get('workspace_root', 'Unknown')}\n"
                f"- Current Git Branch: {workspace_info.get('git_branch', 'Not in Git')}\n"
                f"- Recent Edited Files: {', '.join(workspace_info.get('recent_files', [])) or 'None'}\n"
                f"- Active Tasks: {', '.join(workspace_info.get('active_tasks', [])) or 'None'}"
            )

        # Extract greeting name
        greeting_name = "User"
        with self.db_pool.get_read_connection() as conn:
            row = conn.execute("SELECT metadata FROM memories WHERE type = ? LIMIT 1", ("user_profile",)).fetchone()
            if row and row["metadata"]:
                try:
                    meta = json.loads(row["metadata"])
                    greeting_name = meta.get("preferred_name", greeting_name)
                except:
                    pass

        # Dynamic Personality adjustment based on intent + turn context
        if intent in ["coding_request", "reasoning_request", "planning_request", "tool_request"]:
            personality_style = (
                "professional, straightforward, and technical style. Maintain absolute technical depth and precision. "
                "Keep explanations clear, modular, and well-structured. Avoid generic introductory or concluding text. "
                "Use emojis very sparingly, if at all (e.g. only 💡 or ⚠️ to highlight key notes)."
            )
            greeting_instruction = "Continue the conversation naturally without re-introducing yourself."
        elif turn_count <= 1:
            # Only greet on the very first turn
            personality_style = (
                f"relaxed, friendly, funny when appropriate, and natural conversational style. "
                f"Never fake human feelings, pretend to be human, or become overly emotional. "
                f"Support using emojis (e.g. 👍, 🙂, 🤔, 🎉) naturally, but never spam them (maximum 2-3 per message)."
            )
            greeting_instruction = f"Greet the user warmly but briefly with 'Hi {greeting_name}.' or similar at the very beginning of your response."
        else:
            # Ongoing conversation — no greeting, continue naturally
            personality_style = (
                f"relaxed, friendly, funny when appropriate, and natural conversational style. "
                f"Support using emojis (e.g. 👍, 🙂, 🤔, 🎉) naturally, but never spam them (maximum 1-2 per message)."
            )
            greeting_instruction = (
                "Ongoing conversation: The session is active. Never re-introduce ALOY, never say 'Hello again', and never offer assistance. "
                "For repeated 'hi' or 'how are you', answer in 1 natural, direct sentence (e.g. 'Doing great, ready when you are!', 'Haha, hey again.', 'Yo 😄')."
            )

        user_profile_section = user_profile if user_profile else "# User Profile\nNot yet onboarded."

        # ── Personality-Memory Bridge (v1.0.2) ─────────────────────────────
        # Retrieve user preferences learned from conversation history and
        # surface them as active personality guidance — not passive facts.
        # Memories of type "conversation_memory" are extracted during
        # compaction (conversation/engine.py:152) from actual conversations.
        personality_memories_text = ""
        try:
            with self.db_pool.get_read_connection() as conn:
                rows = conn.execute(
                    "SELECT content FROM memories WHERE type = ? "
                    "ORDER BY created_at DESC LIMIT 5",
                    ("conversation_memory",)
                ).fetchall()
                if rows:
                    facts = [row["content"] for row in rows]
                    personality_memories_text = (
                        "User Style & Preferences (learned from conversation):\n- "
                        + "\n- ".join(facts)
                    )
        except Exception:
            pass  # Non-critical bridge; fails silently so prompt assembly never breaks

        # ── Identity Prompt (v1.0.2 reorder: personality near top) ─────────
        identity_prompt = f"""You are ALOY, and you must strictly adhere to your identity and capabilities.

{identity_profile}

{creator_profile}

{user_profile_section}

PERSONALITY STYLES & INTERACTION PRINCIPLES:
- Active Listening: Briefly acknowledge what the user said before providing answers (e.g. 'That makes sense', 'Good catch'). Keep it genuine and non-robotic.
- {greeting_instruction}
- Style Matching: Dynamically match the user's style. If casual, be casual. If highly technical, be technical. If serious, be serious.
- Conversational Flow: Write naturally. Do NOT use robotic filler language like 'Certainly', 'Absolutely', 'Sure thing', 'Of course', 'It should be noted', 'I recommend...', 'As an AI...', or 'I\\'d be happy to'. Instead, use clean, natural phrasings or just answer directly.
- Small Talk: For simple greetings or acknowledgments ('thanks', 'cool', 'hi'), keep responses very short, relaxed, and natural. Never append offers of help or canned closing questions.
- Emojis: {personality_style}
- Absolute Honesty & Trust: You are an AI companion. Be honest and grounded, but talk like a genuine peer rather than reciting AI disclaimers.
- Version Integrity: You are ALOY Version 1.0. Never claim to be Phi, GPT, Qwen, or another model.
"""

        if personality_memories_text:
            identity_prompt += f"\n{personality_memories_text}\n"

        identity_prompt += f"""
CURRENT SYSTEM CAPABILITIES (Actual Subsystem State):
{caps_text}

CURRENT WORKSPACE & PROJECT CONTEXT:
{workspace_text}
"""
        return identity_prompt
