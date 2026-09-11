import openai
from typing import List, Dict, Any, Optional
from src.app.llm.base import LLMProvider
from src.app.core.config import settings
from src.app.core.logging import logger
from src.app.core.exceptions import ConfigurationException, LLMProviderException
from src.app.core.retry import retry_async


class OpenAIProvider(LLMProvider):
    """
    OpenAI API Provider implementation for LLM completions and embeddings.
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.model = model or settings.DEFAULT_MODEL
        self.embedding_model = settings.EMBEDDING_MODEL
        self.base_url = base_url or settings.OPENAI_BASE_URL
        
        # Check if API key is a valid key (not empty or default placeholder)
        is_placeholder = (
            not self.api_key or 
            "your-openai-api-key" in self.api_key or 
            "your_api" in self.api_key
        )

        if not is_placeholder:
            # retry_async owns retry policy so the SDK must not retry requests again.
            client_kwargs = {
                "api_key": self.api_key,
                "timeout": settings.EXTERNAL_REQUEST_TIMEOUT_SECONDS,
                "max_retries": 0,
            }
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
            self.client = openai.AsyncOpenAI(**client_kwargs)
        else:
            self.client = None
            logger.warning("OpenAI API key is missing or set to placeholder.")

    async def generate_completion(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7
    ) -> Dict[str, Any]:
        """
        Generates completion using OpenAI Chat Completions API.
        """
        if not self.client:
            if not settings.mocks_allowed:
                raise ConfigurationException("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
            # Explicit local-development fallback; production never returns this as an API result.
            logger.info("Generating simulated LLM response (No valid OpenAI API key configured).")
            return {
                "content": f"[Simulated Cloud LLM Response]: Am primit solicitarea: '{prompt}'. Sistemul funcționează corect!",
                "tool_calls": [],
                "usage": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25}
            }

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
                "temperature": temperature,
            }
            if tools:
                kwargs["tools"] = tools

            response = await retry_async(
                lambda: self.client.chat.completions.create(**kwargs),
                operation_name="openai_chat_completion",
            )
            choice = response.choices[0]

            tool_calls_list = []
            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    tool_calls_list.append({
                        "id": tc.id,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    })

            return {
                "content": choice.message.content or "",
                "tool_calls": tool_calls_list,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0,
                }
            }
        except openai.AuthenticationError as auth_err:
            if settings.mocks_allowed:
                logger.warning(
                    "OpenAI authentication failed in development (%s).",
                    type(auth_err).__name__,
                )
                return {
                    "content": f"[Simulated LLM Fallback]: Solicitarea '{prompt}' a fost recepționată cu succes.",
                    "tool_calls": [],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                }
            raise LLMProviderException("OpenAI authentication failed; verify OPENAI_API_KEY") from auth_err
        except Exception as exc:
            logger.warning(
                "OpenAI completion failed (%s: %s). Falling back to local Ollama runtime.",
                type(exc).__name__,
                exc,
            )
            try:
                from src.app.llm.ollama_provider import OllamaProvider
                ollama_fallback = OllamaProvider()
                return await ollama_fallback.generate_completion(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    history=history,
                    tools=tools,
                    temperature=temperature,
                )
            except Exception as fallback_exc:
                logger.error("Local Ollama fallback also failed (%s).", fallback_exc)
                raise LLMProviderException("OpenAI completion request failed") from exc

    async def generate_embeddings(self, text: str) -> List[float]:
        """
        Generates text embedding vector using OpenAI Embeddings API.
        """
        if not self.client:
            if settings.mocks_allowed:
                from src.app.rag.embeddings import MockEmbeddingProvider
                return await MockEmbeddingProvider().embed_text(text)
            raise ConfigurationException("OPENAI_API_KEY is required for OpenAI embeddings")

        try:
            response = await retry_async(
                lambda: self.client.embeddings.create(
                    model=self.embedding_model,
                    input=text
                ),
                operation_name="openai_embedding",
            )
            return response.data[0].embedding
        except openai.AuthenticationError as auth_err:
            if settings.mocks_allowed:
                from src.app.rag.embeddings import MockEmbeddingProvider
                return await MockEmbeddingProvider().embed_text(text)
            raise LLMProviderException("OpenAI embedding authentication failed") from auth_err
        except Exception as exc:
            logger.warning(
                "OpenAI embedding request failed (%s: %s). Falling back to local Ollama embeddings.",
                type(exc).__name__,
                exc,
            )
            try:
                from src.app.llm.ollama_provider import OllamaProvider
                ollama_fallback = OllamaProvider()
                return await ollama_fallback.generate_embeddings(text)
            except Exception as fallback_exc:
                logger.error("Local Ollama embedding fallback also failed (%s).", fallback_exc)
                raise LLMProviderException("OpenAI embedding request failed") from exc
