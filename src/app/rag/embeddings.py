"""Embedding providers used by RAG ingestion and retrieval."""

import hashlib
import math
from abc import ABC, abstractmethod
from typing import List, Optional

import openai

from src.app.core.config import settings
from src.app.core.exceptions import ConfigurationException, RAGRetrievalException
from src.app.core.logging import logger
from src.app.core.retry import retry_async


class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed_text(self, text: str) -> List[float]:
        pass

    @abstractmethod
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        pass


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.model = model or settings.EMBEDDING_MODEL
        self.client = None
        if self.api_key and "your-openai-api-key" not in self.api_key and "your_api" not in self.api_key:
            self.client = openai.AsyncOpenAI(
                api_key=self.api_key,
                timeout=settings.EXTERNAL_REQUEST_TIMEOUT_SECONDS,
                max_retries=0,
            )

    async def embed_text(self, text: str) -> List[float]:
        return (await self.embed_batch([text]))[0]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not self.client:
            raise ConfigurationException("OPENAI_API_KEY is required for EMBEDDING_PROVIDER=openai")
        try:
            response = await retry_async(
                lambda: self.client.embeddings.create(model=self.model, input=texts),
                operation_name="openai_embedding_batch",
            )
            vectors = [item.embedding for item in response.data]
            if len(vectors) != len(texts):
                raise RAGRetrievalException("OpenAI returned an unexpected embedding count")
            return vectors
        except Exception as exc:
            if isinstance(exc, RAGRetrievalException):
                raise
            logger.error("OpenAI embedding request failed (%s).", type(exc).__name__)
            raise RAGRetrievalException("OpenAI embedding request failed") from exc


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Use Ollama's native embedding API when an on-premise model is selected."""

    def __init__(self, model: Optional[str] = None, client=None):
        import ollama

        self.model = model or settings.EMBEDDING_MODEL
        self.client = client or ollama.AsyncClient(
            host=settings.OLLAMA_BASE_URL,
            timeout=settings.OLLAMA_REQUEST_TIMEOUT_SECONDS,
        )

    async def embed_text(self, text: str) -> List[float]:
        return (await self.embed_batch([text]))[0]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        try:
            response = await retry_async(
                lambda: self.client.embed(model=self.model, input=texts),
                operation_name="ollama_embedding_batch",
            )
            vectors = response.get("embeddings", []) if isinstance(response, dict) else response.embeddings
            if len(vectors) != len(texts):
                raise RAGRetrievalException("Ollama returned an unexpected embedding count")
            return vectors
        except Exception as exc:
            if isinstance(exc, RAGRetrievalException):
                raise
            logger.error("Ollama embedding request failed (%s).", type(exc).__name__)
            raise RAGRetrievalException("Ollama embedding request failed") from exc


class MockEmbeddingProvider(EmbeddingProvider):
    """Deterministic embeddings reserved for unit tests and explicit local mocks."""

    def _generate_deterministic_vector(self, text: str, dimension: Optional[int] = None) -> List[float]:
        dimension = dimension or settings.EMBEDDING_VECTOR_SIZE
        seed_hash = hashlib.sha256(text.encode("utf-8")).digest()
        vector = [((seed_hash[index % len(seed_hash)] + index) % 256 - 128) / 128.0 for index in range(dimension)]
        magnitude = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / magnitude for value in vector]

    async def embed_text(self, text: str) -> List[float]:
        return self._generate_deterministic_vector(text)

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [self._generate_deterministic_vector(text) for text in texts]


_mock_embedding_instance = MockEmbeddingProvider()


def get_embedding_provider() -> EmbeddingProvider:
    provider_name = settings.EMBEDDING_PROVIDER.lower()
    if provider_name == "mock":
        if settings.mocks_allowed:
            return _mock_embedding_instance
        raise ConfigurationException("EMBEDDING_PROVIDER=mock is not allowed in production")
    if provider_name == "openai":
        provider = OpenAIEmbeddingProvider()
        if provider.client is not None:
            return provider
        if settings.mocks_allowed:
            logger.warning("OpenAI embedding key is missing; using explicit development mock embeddings.")
            return _mock_embedding_instance
        raise ConfigurationException("OPENAI_API_KEY is required for EMBEDDING_PROVIDER=openai")
    if provider_name == "ollama":
        return OllamaEmbeddingProvider()
    raise ConfigurationException(f"Unsupported embedding provider: {provider_name}")
