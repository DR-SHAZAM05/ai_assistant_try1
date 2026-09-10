from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class LLMProvider(ABC):
    """
    Abstract Base Class for LLM Providers (OpenAI, Gemini, Ollama).
    Ensures Business Logic remains independent of specific Cloud or Local LLM implementations.
    """

    @abstractmethod
    async def generate_completion(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7
    ) -> Dict[str, Any]:
        """
        Generate text completion or tool call recommendation.
        Returns dictionary containing:
        - "content": str (response text)
        - "tool_calls": list (optional tool calls)
        - "usage": dict (token usage metrics)
        """
        pass

    @abstractmethod
    async def generate_embeddings(
        self,
        text: str
    ) -> List[float]:
        """
        Generate vector embedding representation for text.
        """
        pass
