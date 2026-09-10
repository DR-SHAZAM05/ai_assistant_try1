import pytest
from src.app.llm.openai_provider import OpenAIProvider
from src.app.core.config import settings
from src.app.core.exceptions import LLMProviderException


@pytest.mark.asyncio
async def test_openai_provider_completion():
    provider = OpenAIProvider()
    result = await provider.generate_completion(
        prompt="Salut! Ce poți face?",
        system_prompt="Test system prompt"
    )

    assert "content" in result
    assert isinstance(result["content"], str)
    assert len(result["content"]) > 0


@pytest.mark.asyncio
async def test_openai_provider_does_not_expose_external_error_details(monkeypatch):
    class FailingCompletions:
        async def create(self, **kwargs):
            raise RuntimeError("token=must-not-appear-in-user-visible-error")

    class FailingClient:
        class Chat:
            completions = FailingCompletions()

        chat = Chat()

    monkeypatch.setattr(settings, "ALLOW_MOCK_PROVIDERS", False)
    monkeypatch.setattr(settings, "EXTERNAL_RETRY_ATTEMPTS", 1)
    provider = OpenAIProvider(api_key="unit-test-openai-key")
    provider.client = FailingClient()

    with pytest.raises(LLMProviderException) as exc_info:
        await provider.generate_completion(prompt="test")

    assert str(exc_info.value) == "OpenAI completion request failed"
    assert "must-not-appear" not in str(exc_info.value)
