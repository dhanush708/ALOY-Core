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
