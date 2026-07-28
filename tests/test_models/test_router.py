import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from models.router import ModelRouter, ROUTING_TABLE
from models.tracker import ModelTracker, ModelHealth
from models.coordinator import ModelCoordinator, Priority
from models.ollama_client import OllamaClient


# ======================================================================
# ModelTracker tests
# ======================================================================
class TestModelTracker:
    def test_record_success(self):
        t = ModelTracker()
        t.record_success("qwen3:8b", "simple_chat", 120.5)
        t.record_success("qwen3:8b", "simple_chat", 80.0)
        h = t.get_health("qwen3:8b")
        assert h.total_calls == 2
        assert h.error_count == 0
        assert h.status == "healthy"
        assert h.avg_latency_ms == pytest.approx(100.25)

    def test_record_error_degrades(self):
        t = ModelTracker()
        for _ in range(8):
            t.record_success("m", "t", 100)
        for _ in range(2):
            t.record_error("m", "t")
        h = t.get_health("m")
        assert h.error_rate == pytest.approx(0.2)
        assert h.status == "degraded"

    def test_unhealthy(self):
        t = ModelTracker()
        for _ in range(7):
            t.record_success("m", "t", 100)
        for _ in range(3):
            t.record_error("m", "t")
        h = t.get_health("m")
        assert h.status == "unhealthy"

    def test_is_degraded(self):
        t = ModelTracker()
        assert t.is_degraded("m") is False
        for _ in range(5):
            t.record_error("m", "t")
        assert t.is_degraded("m") is True


# ======================================================================
# ModelCoordinator tests
# ======================================================================
class TestModelCoordinator:
    @pytest.mark.asyncio
    async def test_acquire_release(self):
        c = ModelCoordinator(max_concurrent=1)
        assert c.is_busy() is False
        await c.acquire(Priority.CONVERSATION)
        assert c.is_busy() is True
        await c.release()
        assert c.is_busy() is False


# ======================================================================
# ModelRouter tests
# ======================================================================
class TestModelRouter:
    def test_resolve_model_default(self):
        r = ModelRouter()
        from models.config import MODELS_CONFIG
        
        # Test unaffected core routes
        assert r.resolve_model("simple_chat") == ROUTING_TABLE["simple_chat"]["primary"]
        assert r.resolve_model("coding_request") == ROUTING_TABLE["coding_request"]["primary"]
        assert r.resolve_model("reasoning_request") == ROUTING_TABLE["reasoning_request"]["primary"]
        
        # Test updated memory_query route
        assert r.resolve_model("memory_query") == MODELS_CONFIG["chat"]["name"]
        
        # Regression checks for unchanged vision/search
        assert r.resolve_model("simple_chat") == MODELS_CONFIG["vision"]["name"]
        assert r.resolve_model("live_search_query") == MODELS_CONFIG["vision"]["name"]

    def test_resolve_model_conversation_continuity(self):
        r = ModelRouter()
        primary = ROUTING_TABLE["simple_chat"]["primary"]
        fallback = ROUTING_TABLE["simple_chat"]["fallback"]
        
        # Simulate a prior conversation binding to primary
        r._conversation_models["conv1"] = primary
        assert r.resolve_model("simple_chat", conversation_id="conv1") == primary
        
        # Simulate a prior conversation binding to a different intent's primary
        r._conversation_models["conv2"] = ROUTING_TABLE["memory_query"]["primary"]
        # It should ignore the bound model and use simple_chat's primary
        assert r.resolve_model("simple_chat", conversation_id="conv2") == primary

    @pytest.mark.asyncio
    async def test_generate_success(self):
        r = ModelRouter()
        r.client = MagicMock()
        r.client.generate = AsyncMock(return_value="Hello world")
        result = await r.generate("simple_chat", "Hi")
        assert result == "Hello world"
        primary = ROUTING_TABLE["simple_chat"]["primary"]
        assert r.tracker.get_health(primary).total_calls == 1
        assert r.tracker.get_health(primary).status == "healthy"

    @pytest.mark.asyncio
    async def test_generate_fallback(self):
        r = ModelRouter()
        r.client = MagicMock()
        call_count = 0
        primary = ROUTING_TABLE["simple_chat"]["primary"]

        async def mock_generate(model, prompt, options=None, **kwargs):
            nonlocal call_count
            call_count += 1
            if model == primary:
                raise RuntimeError("Primary failed")
            return "Fallback response"

        r.client.generate = mock_generate
        result = await r.generate("simple_chat", "Hi")
        assert result == "Fallback response"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_generate_conversation_continuity(self):
        r = ModelRouter()
        r.client = MagicMock()
        r.client.generate = AsyncMock(return_value="OK")
        await r.generate("simple_chat", "Hi", conversation_id="c1")
        # The model used should now be bound to the conversation
        primary = ROUTING_TABLE["simple_chat"]["primary"]
        assert r._conversation_models["c1"] == primary

    @pytest.mark.asyncio
    async def test_stream_success(self):
        r = ModelRouter()
        r.client = MagicMock()

        async def mock_stream(model, prompt, options=None, **kwargs):
            for t in ["Hello", " ", "World"]:
                yield t

        r.client.stream = mock_stream
        tokens = []
        async for tok in r.stream("simple_chat", "Hi"):
            tokens.append(tok)
        assert "".join(tokens) == "Hello World"

    def test_clear_conversation(self):
        r = ModelRouter()
        r._conversation_models["c1"] = "qwen3:8b"
        r.clear_conversation("c1")
        assert "c1" not in r._conversation_models

    def test_is_busy(self):
        r = ModelRouter()
        assert r.is_busy() is False

    # ------------------------------------------------------------------
    # H1 regression tests — pre-stream degradation gate (v1.0.2)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_stream_chat_routes_to_fallback_when_primary_degraded(self):
        """stream_chat() must use the fallback model when the primary is degraded."""
        r = ModelRouter()
        primary = ROUTING_TABLE["simple_chat"]["primary"]
        fallback = ROUTING_TABLE["simple_chat"]["fallback"]

        # Drive the primary's error rate above the degradation threshold
        for _ in range(4):
            r.tracker.record_error(primary, "simple_chat")
        for _ in range(6):
            r.tracker.record_success(primary, "simple_chat", 100)
        # 4 errors / 10 calls = 40 % → unhealthy
        assert r.tracker.is_degraded(primary)

        models_used = []

        async def mock_chat_stream(model, messages, options=None, **kwargs):
            models_used.append(model)
            yield "ok"

        r.client.chat_stream = mock_chat_stream
        messages = [{"role": "user", "content": "hi"}]
        tokens = []
        async for tok in r.stream_chat("simple_chat", messages):
            tokens.append(tok)

        assert models_used == [fallback], (
            f"Degraded primary should route to fallback '{fallback}', got {models_used}"
        )
        assert tokens == ["ok"]

    @pytest.mark.asyncio
    async def test_stream_chat_does_not_replace_healthy_primary(self):
        """stream_chat() must keep the primary when it is healthy."""
        r = ModelRouter()
        primary = ROUTING_TABLE["simple_chat"]["primary"]
        assert not r.tracker.is_degraded(primary)

        models_used = []

        async def mock_chat_stream(model, messages, options=None, **kwargs):
            models_used.append(model)
            yield "hello"

        r.client.chat_stream = mock_chat_stream
        messages = [{"role": "user", "content": "hi"}]
        async for _ in r.stream_chat("simple_chat", messages):
            pass

        assert models_used == [primary], (
            f"Healthy primary should be used directly, got {models_used}"
        )

    @pytest.mark.asyncio
    async def test_stream_chat_degraded_replaces_conversation_binding(self):
        """When the degraded model has a conversation-continuity binding, that binding is updated to the fallback."""
        r = ModelRouter()
        primary = ROUTING_TABLE["simple_chat"]["primary"]
        fallback = ROUTING_TABLE["simple_chat"]["fallback"]

        # Lock the conversation to the (soon-to-be-degraded) primary
        r._conversation_models["conv_x"] = primary

        # Degrade the primary
        for _ in range(5):
            r.tracker.record_error(primary, "simple_chat")
        assert r.tracker.is_degraded(primary)

        async def mock_chat_stream(model, messages, options=None, **kwargs):
            yield "ok"

        r.client.chat_stream = mock_chat_stream
        messages = [{"role": "user", "content": "test"}]
        async for _ in r.stream_chat("simple_chat", messages, conversation_id="conv_x"):
            pass

        # Binding must have been updated to the fallback model
        assert r._conversation_models.get("conv_x") == fallback, (
            "Conversation binding to a degraded model must be replaced by the fallback model after rerouting"
        )
