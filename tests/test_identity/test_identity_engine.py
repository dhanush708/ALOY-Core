import pytest
import pytest_asyncio
from database.connection import DatabaseConnectionPool
from database.migrator import Migrator
from memory.manager import MemoryManager
from identity.engine import IdentityEngine

@pytest_asyncio.fixture
async def setup_subsystems(tmp_path):
    db_path = str(tmp_path / "test_identity.db")
    pool = DatabaseConnectionPool(db_path)
    
    migrator = Migrator(pool, migrations_pkg="database.migrations")
    await migrator.migrate()
    
    manager = MemoryManager(pool)
    await manager.start()
    
    # Mock embedding generator
    from unittest.mock import AsyncMock
    manager.embeddings.generate = AsyncMock(return_value=[0.1] * 768)
    
    engine = IdentityEngine(pool, manager)
    return pool, manager, engine

@pytest.mark.asyncio
async def test_seeding_and_loading(setup_subsystems):
    pool, manager, engine = setup_subsystems
    
    # Verify profiles are seeded
    await engine.initialize_if_needed()
    
    # Check that they exist in DB
    founder_content = await engine.load_founder_profile()
    identity_content = await engine.load_identity_profile()
    
    assert "Dhanush A" in founder_content
    assert "github.com/dhanush708" in founder_content
    assert "ALOY Identity Profile" in identity_content
    assert "Creator: Dhanush A" in identity_content
    
    # Now save a user profile and verify it loads
    await engine.save_user_profile(
        name="Alice Smith",
        preferred_name="Alice",
        age=25,
        country="US",
        preferences="Likes Python"
    )
    user_content = await engine.load_founder_profile()
    assert "Alice" in user_content
    assert "Likes Python" in user_content

    # Re-running initialize_if_needed shouldn't cause errors or duplicate seeding
    await engine.initialize_if_needed()
    
    # Query database directly to count profile entries
    with pool.get_read_connection() as conn:
        creator_rows = conn.execute("SELECT COUNT(*) as cnt FROM memories WHERE type = 'creator_profile'").fetchone()
        identity_rows = conn.execute("SELECT COUNT(*) as cnt FROM memories WHERE type = 'identity_profile'").fetchone()
        assert creator_rows["cnt"] == 1
        assert identity_rows["cnt"] == 1

@pytest.mark.asyncio
async def test_capability_status(setup_subsystems):
    pool, manager, engine = setup_subsystems
    
    # Test default/none state
    caps = engine.get_capability_status(None)
    assert caps["Conversation"] is False
    assert caps["Memory"] is False
    
    # Mock an app state
    class MockAppState:
        def __init__(self):
            self.engine = object()
            self.memory_manager = manager
            self.project_manager = object()
            self.evolution_engine = object()
            self.knowledge_router = object()
            self.doc_intelligence = object()
            
            # Setup agent runtime mock
            class MockAgentRuntime:
                def __init__(self):
                    class MockToolSystem:
                        def __init__(self):
                            class Meta:
                                def __init__(self, name):
                                     self.name = name
                            self._tools = [Meta("web_search"), Meta("image_reader"), Meta("run_command")]

                        def list_tools(self):
                            class Meta:
                                def __init__(self, name):
                                     self.name = name
                            return [Meta("web_search"), Meta("image_reader"), Meta("run_command")]

                    self.tool_system = MockToolSystem()
            self.agent_runtime = MockAgentRuntime()
            self.reasoning_engine = object()

    app_state = MockAppState()
    caps = engine.get_capability_status(app_state)
    
    assert caps["Conversation"] is True
    assert caps["Memory"] is True
    assert caps["Projects"] is True
    assert caps["Agent Runtime"] is True
    assert caps["Tool System"] is True
    assert caps["Internet Research"] is True
    assert caps["Vision"] is True
    assert caps["Evolution"] is True
    assert caps["MCP"] is False
    assert caps["Speech"] is False

@pytest.mark.asyncio
async def test_identity_prompt_generation(setup_subsystems):
    pool, manager, engine = setup_subsystems
    await engine.initialize_if_needed()
    
    # Seed a mock user profile resembling a standard user
    await engine.save_user_profile(
        name="John Doe",
        preferred_name="John",
        age=30,
        country="USA",
        preferences="Laptop: Developer Workstation"
    )
    
    # 1. Casual intent should prompt friendly style
    prompt = await engine.generate_identity_prompt("simple_chat")
    assert "Hi John." in prompt
    assert "relaxed, friendly" in prompt
    assert "Developer Workstation" in prompt
    
    # 2. Technical intent should prompt professional style
    prompt = await engine.generate_identity_prompt("coding_request")
    assert "professional, straightforward, and technical style" in prompt
    assert "John" in prompt
    
    # 3. Dynamic workspace context inclusion
    workspace_info = {
        "project_name": "TestProject",
        "workspace_root": "/absolute/path/to/test",
        "git_branch": "main",
        "recent_files": ["server.py", "engine.py"],
        "active_tasks": ["Implement database router"]
    }
    prompt_with_workspace = await engine.generate_identity_prompt("simple_chat", workspace_info=workspace_info)
    assert "TestProject" in prompt_with_workspace
    assert "server.py, engine.py" in prompt_with_workspace
    assert "main" in prompt_with_workspace


# =============================================================================
# Personality Recovery v1.0.2 Regression Tests
# =============================================================================

@pytest.mark.asyncio
async def test_personality_memory_bridge_injects_conversation_memories(setup_subsystems):
    """When conversation_memory entries exist, they must appear in the
    identity prompt as active personality guidance."""
    pool, manager, engine = setup_subsystems
    await engine.initialize_if_needed()

    # Seed conversation_memory entries simulating compaction-extracted facts
    await manager.store(
        type="conversation_memory",
        content="User prefers short, direct answers without fluff.",
        tier="short_term",
        importance=0.6,
        metadata={"source_conversation_id": "c_test"}
    )
    await manager.store(
        type="conversation_memory",
        content="User works primarily in Python and TypeScript.",
        tier="short_term",
        importance=0.6
    )

    prompt = await engine.generate_identity_prompt("simple_chat", turn_count=2)
    assert "User Style & Preferences (learned from conversation)" in prompt
    assert "User prefers short, direct answers without fluff." in prompt
    assert "User works primarily in Python and TypeScript." in prompt


@pytest.mark.asyncio
async def test_personality_memory_bridge_empty_when_no_memories(setup_subsystems):
    """When no conversation_memory entries exist, the bridge must not inject
    an empty section."""
    pool, manager, engine = setup_subsystems
    await engine.initialize_if_needed()

    prompt = await engine.generate_identity_prompt("simple_chat", turn_count=2)
    assert "User Style & Preferences (learned from conversation)" not in prompt


@pytest.mark.asyncio
async def test_personality_styles_before_capabilities_in_prompt(setup_subsystems):
    """v1.0.2 reorder: PERSONALITY STYLES section must appear before
    CURRENT SYSTEM CAPABILITIES in the assembled prompt."""
    pool, manager, engine = setup_subsystems
    await engine.initialize_if_needed()

    prompt = await engine.generate_identity_prompt("simple_chat", turn_count=2)

    personality_idx = prompt.find("PERSONALITY STYLES & INTERACTION PRINCIPLES")
    capabilities_idx = prompt.find("CURRENT SYSTEM CAPABILITIES")
    workspace_idx = prompt.find("CURRENT WORKSPACE & PROJECT CONTEXT")

    assert personality_idx != -1, "Personality section must exist"
    assert capabilities_idx != -1, "Capabilities section must exist"

    # Personality BEFORE capabilities
    assert personality_idx < capabilities_idx, (
        "Personality must appear BEFORE capabilities "
        f"(personality at {personality_idx}, capabilities at {capabilities_idx})"
    )
    # Capabilities BEFORE workspace (sanity check on ordering)
    assert capabilities_idx < workspace_idx, (
        "Capabilities must appear BEFORE workspace"
    )


@pytest.mark.asyncio
async def test_personality_memory_bridge_respects_limit_5(setup_subsystems):
    """The bridge must retrieve at most 5 conversation_memory entries even
    when more exist."""
    pool, manager, engine = setup_subsystems
    await engine.initialize_if_needed()

    # Seed 10 entries
    for i in range(10):
        await manager.store(
            type="conversation_memory",
            content=f"Memory fact number {i} about user style.",
            tier="short_term",
            importance=0.5
        )

    prompt = await engine.generate_identity_prompt("simple_chat", turn_count=2)

    # Count occurrences of "Memory fact number" in the prompt
    count = prompt.count("Memory fact number")
    assert count <= 5, f"Bridge must show at most 5 entries but found {count}"
    assert count >= 1, f"Bridge must show at least 1 entry but found {count}"


def test_integrity_filter_preserves_personality_memories():
    """The PromptIntegrityFilter must NOT strip the new bridge section
    'User Style & Preferences (learned from conversation)' or its content."""
    from identity.integrity import PromptIntegrityFilter

    bridge_content = """User Style & Preferences (learned from conversation):
- User prefers short, direct answers without fluff.
- User works primarily in Python and TypeScript."""

    # 1. Full-text clean must leave bridge content intact
    filt = PromptIntegrityFilter()
    cleaned = filt.clean_text(bridge_content)
    assert "User Style & Preferences" in cleaned
    assert "User prefers short, direct answers" in cleaned
    assert "Python and TypeScript" in cleaned

    # 2. The response-start sanitizer must not strip it either
    filt2 = PromptIntegrityFilter()
    sanitized = filt2.sanitize_response_start(bridge_content)
    assert "User Style & Preferences" in sanitized
    assert "User prefers short, direct answers" in sanitized

    # 3. Streaming process_chunk must pass it through
    filt3 = PromptIntegrityFilter()
    tokens = []
    for chunk in ["User Style & Preferences ", "(learned from conversation):\n",
                  "- User prefers short, ", "direct answers without fluff.\n",
                  "- User works primarily in Python and TypeScript."]:
        clean = filt3.process_chunk(chunk)
        if clean:
            tokens.append(clean)
    final = filt3.flush()
    if final:
        tokens.append(final)
    assembled = "".join(tokens)
    assert "User Style & Preferences" in assembled
    assert "Python and TypeScript" in assembled
