import pytest

from src.app.llm.ollama_provider import OllamaProvider
from src.app.llm.factory import get_llm_provider


class FakeOllamaClient:
    async def chat(self, **kwargs):
        return {
            "message": {"content": "Răspuns local Ollama", "tool_calls": []},
            "prompt_eval_count": 7,
            "eval_count": 5,
        }

    async def embed(self, **kwargs):
        return {"embeddings": [[0.1, 0.2, 0.3]]}


class FailingOllamaClient:
    async def chat(self, **kwargs):
        raise RuntimeError("connection refused")

    async def embed(self, **kwargs):
        raise RuntimeError("connection refused")


@pytest.mark.asyncio
async def test_ollama_provider_completion_with_fake_client():
    provider = OllamaProvider(client=FakeOllamaClient(), model="llama-test")

    result = await provider.generate_completion("Salut", system_prompt="Test")

    assert result["content"] == "Răspuns local Ollama"
    assert result["usage"]["total_tokens"] == 12


@pytest.mark.asyncio
async def test_ollama_provider_fallback_when_runtime_unavailable():
    provider = OllamaProvider(client=FailingOllamaClient(), model="llama-test")

    result = await provider.generate_completion("Salut")

    assert "Simulated Local LLM Response" in result["content"]
    assert result["usage"]["total_tokens"] == 0


@pytest.mark.asyncio
async def test_ollama_provider_embeddings_with_fake_client():
    provider = OllamaProvider(client=FakeOllamaClient(), model="llama-test")

    vector = await provider.generate_embeddings("text")

    assert vector == [0.1, 0.2, 0.3]


def test_llm_factory_returns_ollama_provider():
    provider = get_llm_provider("ollama")
    assert isinstance(provider, OllamaProvider)
