from typing import Dict, Any, Callable, Optional
from src.app.core.logging import logger


class ToolRegistry:
    """
    Registry for tools and specialized agents that can be called by AIOrchestrator.
    """
    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}

    def register_tool(self, name: str, description: str, func: Callable, parameters: Optional[Dict[str, Any]] = None):
        """
        Registers a tool function with JSON schema definition for LLM tool calling.
        """
        self._tools[name] = {
            "name": name,
            "description": description,
            "func": func,
            "parameters": parameters or {"type": "object", "properties": {}}
        }
        logger.info(f"Registered tool in AI Orchestrator: '{name}'")

    def get_tool_definitions(self) -> list:
        """
        Returns tool definitions formatted for OpenAI / Gemini function calling API.
        """
        definitions = []
        for tool_name, tool_data in self._tools.items():
            definitions.append({
                "type": "function",
                "function": {
                    "name": tool_data["name"],
                    "description": tool_data["description"],
                    "parameters": tool_data["parameters"]
                }
            })
        return definitions

    async def execute_tool(self, name: str, **kwargs) -> Any:
        """
        Executes a registered tool by name.
        """
        if name not in self._tools:
            raise ValueError(f"Tool '{name}' is not registered.")
        
        logger.info("Executing tool '%s'.", name)
        tool_func = self._tools[name]["func"]
        return await tool_func(**kwargs)


global_tool_registry = ToolRegistry()
