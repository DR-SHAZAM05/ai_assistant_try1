from src.app.llm.base import LLMProvider
from src.app.llm.openai_provider import OpenAIProvider
from src.app.llm.ollama_provider import OllamaProvider
from src.app.core.config import settings
from src.app.core.exceptions import ConfigurationException


def get_llm_provider(provider_name: str = None) -> LLMProvider:
    """
    Factory function to retrieve the configured LLMProvider instance.
    Supports the explicitly implemented 'openai' and 'ollama' providers.
    """
    provider = (provider_name or settings.LLM_PROVIDER).lower()

    if provider == "openai":
        return OpenAIProvider()
    if provider == "ollama":
        return OllamaProvider()
    raise ConfigurationException(f"Unsupported LLM_PROVIDER: {provider}")
