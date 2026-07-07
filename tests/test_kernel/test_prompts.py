import pytest
import pytest_asyncio
from database.connection import DatabaseConnectionPool
from database.migrator import Migrator
from kernel.prompts import PromptRegistry, PromptTemplate

@pytest_asyncio.fixture
async def db_pool(tmp_path):
    db_path = str(tmp_path / "test_prompts.db")
    pool = DatabaseConnectionPool(db_path)
    # Run migrations to make sure tables exist
    migrator = Migrator(pool, migrations_pkg="database.migrations")
    await migrator.migrate()
    yield pool

@pytest.mark.asyncio
async def test_prompt_template_rendering():
    p = PromptTemplate(
        name="test",
        version="1.0",
        template="Hello {name}!",
        variables=["name"],
        model_hint="model",
        metadata={}
    )
    assert p.render(name="World") == "Hello World!"
    
    # Missing variable should raise ValueError
    with pytest.raises(ValueError):
        p.render()

@pytest.mark.asyncio
async def test_prompt_registry_register_and_get(db_pool):
    registry = PromptRegistry(db_pool)
    await registry.start()
    
    registry.register(
        name="test.prompt",
        version="1.0",
        template="Hello {user}",
        variables=["user"],
        model_hint="gemma"
    )
    
    # Retrieve latest
    p = registry.get("test.prompt", "latest")
    assert p.name == "test.prompt"
    assert p.version == "1.0"
    assert p.template == "Hello {user}"
    assert p.variables == ["user"]
    assert p.model_hint == "gemma"
    
    # Retrieve specific version
    p2 = registry.get("test.prompt", "1.0")
    assert p2 == p

@pytest.mark.asyncio
async def test_prompt_registry_multiple_versions(db_pool):
    registry = PromptRegistry(db_pool)
    await registry.start()
    
    # Register v1
    registry.register(name="multi.prompt", version="1.0", template="v1")
    # Register v2 as active
    registry.register(name="multi.prompt", version="2.0", template="v2", set_active=True)
    # Register v3 but not active
    registry.register(name="multi.prompt", version="3.0", template="v3", set_active=False)
    
    # latest should be v2
    assert registry.get("multi.prompt", "latest").version == "2.0"
    
    # Get v1, v2, v3
    assert registry.get("multi.prompt", "1.0").template == "v1"
    assert registry.get("multi.prompt", "2.0").template == "v2"
    assert registry.get("multi.prompt", "3.0").template == "v3"
    
    # List versions
    versions = registry.list_versions("multi.prompt")
    assert "1.0" in versions
    assert "2.0" in versions
    assert "3.0" in versions
    
    # Set active version to 3.0
    registry.set_active_version("multi.prompt", "3.0")
    assert registry.get("multi.prompt", "latest").version == "3.0"

@pytest.mark.asyncio
async def test_prompt_registry_metrics(db_pool):
    registry = PromptRegistry(db_pool)
    await registry.start()
    
    registry.register(name="metric.prompt", version="1.0", template="test")
    
    # Record some metrics
    registry.record_metric("metric.prompt", "1.0", "latency", 10.0)
    registry.record_metric("metric.prompt", "1.0", "latency", 20.0)
    
    # Check values in DB
    with db_pool.get_read_connection() as conn:
        row = conn.execute(
            "SELECT * FROM prompt_metrics WHERE prompt_name = ? AND prompt_version = ?",
            ("metric.prompt", "1.0")
        ).fetchone()
        assert row is not None
        assert row["metric_name"] == "latency"
        assert row["metric_value"] == 15.0  # Average of 10 and 20
        assert row["sample_count"] == 2
