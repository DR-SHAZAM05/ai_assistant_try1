from src.app.llm.base import LLMProvider
from src.app.llm.openai_provider import OpenAIProvider
from src.app.llm.ollama_provider import OllamaProvider
from src.app.core.config import settings
from src.app.core.exceptions import ConfigurationException


def get_llm_provider(provider_name: str = None) -> LLMProvider:
    """
    Factory function to retrieve the configured LLMProvider instance.
    Supports 'openai', 'ollama', and 'gemini' (via Google's OpenAI-compatible endpoint).
    """
    provider = (provider_name or settings.LLM_PROVIDER).lower()

    if provider == "openai":
        return OpenAIProvider()
    if provider == "gemini":
        gemini_url = settings.OPENAI_BASE_URL or "https://generativelanguage.googleapis.com/v1beta/openai/"
        return OpenAIProvider(base_url=gemini_url)
    if provider == "ollama":
        return OllamaProvider()
    raise ConfigurationException(f"Unsupported LLM_PROVIDER: {provider}")
