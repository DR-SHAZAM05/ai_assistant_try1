from src.app.orchestrator.orchestrator import AIOrchestrator
from src.app.integrations.telegram.service import TelegramService
from src.app.memory.conversation_memory import ConversationMemoryService
from src.app.llm.factory import get_llm_provider


def get_orchestrator_dependency() -> AIOrchestrator:
    """FastAPI dependency for obtaining AIOrchestrator instance."""
    llm_provider = get_llm_provider()
    return AIOrchestrator(llm_provider=llm_provider)


def get_telegram_service_dependency() -> TelegramService:
    """FastAPI dependency for obtaining TelegramService instance."""
    return TelegramService()


def get_conversation_memory_service_dependency() -> ConversationMemoryService:
    """FastAPI dependency for obtaining ConversationMemoryService instance."""
    return ConversationMemoryService()

