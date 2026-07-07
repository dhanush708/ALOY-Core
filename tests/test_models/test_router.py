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
        assert r.resolve_model("simple_chat") == ROUTING_TABLE["simple_chat"]["primary"]
        assert r.resolve_model("coding_request") == ROUTING_TABLE["coding_request"]["primary"]
        assert r.resolve_model("reasoning_request") == ROUTING_TABLE["reasoning_request"]["primary"]

    def test_resolve_model_conversation_continuity(self):
        r = ModelRouter()
        # Simulate a prior conversation binding
        r._conversation_models["conv1"] = "gemma4:e4b"
        assert r.resolve_model("simple_chat", conversation_id="conv1") == "gemma4:e4b"
        # Without conversation_id, should return default
        assert r.resolve_model("simple_chat") == ROUTING_TABLE["simple_chat"]["primary"]

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
