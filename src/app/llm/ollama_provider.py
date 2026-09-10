from typing import List, Dict, Any, Optional

import ollama

from src.app.core.config import settings
from src.app.core.exceptions import LLMProviderException
from src.app.core.logging import logger
from src.app.core.retry import retry_async
from src.app.llm.base import LLMProvider


class OllamaProvider(LLMProvider):
    """
    Local LLM provider backed by an Ollama runtime.
    The rest of the application talks only to LLMProvider, so switching between
    OpenAI and Ollama is controlled by LLM_PROVIDER in .env.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        embedding_model: Optional[str] = None,
        client=None,
    ):
        self.base_url = base_url or settings.OLLAMA_BASE_URL
        self.model = model or settings.OLLAMA_MODEL
        self.embedding_model = embedding_model or settings.EMBEDDING_MODEL
        self.client = client or ollama.AsyncClient(
            host=self.base_url,
            timeout=settings.OLLAMA_REQUEST_TIMEOUT_SECONDS,
        )

    async def generate_completion(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7
    ) -> Dict[str, Any]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        try:
            kwargs = {
                "model": self.model,
                "messages": messages,
                "options": {"temperature": temperature},
            }
            if tools:
                kwargs["tools"] = tools
            response = await retry_async(
                lambda: self.client.chat(**kwargs), operation_name="ollama_chat_completion"
            )
            content = self._get_nested(response, "message", "content") or ""
            return {
                "content": content,
                "tool_calls": self._get_nested(response, "message", "tool_calls") or [],
                "usage": {
                    "prompt_tokens": self._get_value(response, "prompt_eval_count", 0),
                    "completion_tokens": self._get_value(response, "eval_count", 0),
                    "total_tokens": self._get_value(response, "prompt_eval_count", 0) + self._get_value(response, "eval_count", 0),
                }
            }
        except Exception as exc:
            if not settings.mocks_allowed:
                raise LLMProviderException("Ollama completion failed") from exc
            logger.warning("Ollama completion unavailable at %s (%s). Using local fallback response.", self.base_url, type(exc).__name__)
            return {
                "content": f"[Simulated Local LLM Response]: Am primit solicitarea: '{prompt}'. Runtime-ul Ollama nu este disponibil momentan.",
                "tool_calls": [],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            }

    async def generate_embeddings(self, text: str) -> List[float]:
        try:
            response = await retry_async(
                lambda: self.client.embed(
                    model=self.embedding_model,
                    input=text,
                    dimensions=settings.EMBEDDING_VECTOR_SIZE,
                ),
                operation_name="ollama_embedding",
            )
            embeddings = self._get_value(response, "embeddings", [])
            if embeddings and isinstance(embeddings[0], list):
                return embeddings[0]
            raise LLMProviderException("Ollama returned no embeddings")
        except Exception as exc:
            if not settings.mocks_allowed:
                raise LLMProviderException("Ollama embeddings failed") from exc
            from src.app.rag.embeddings import MockEmbeddingProvider
            logger.warning("Ollama embeddings unavailable at %s (%s). Using development mock embedding.", self.base_url, type(exc).__name__)
            return await MockEmbeddingProvider().embed_text(text)

    @staticmethod
    def _get_value(obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    @classmethod
    def _get_nested(cls, obj: Any, *keys: str) -> Any:
        current = obj
        for key in keys:
            current = cls._get_value(current, key)
            if current is None:
                return None
        return current
