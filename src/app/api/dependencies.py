from src.app.orchestrator.orchestrator import AIOrchestrator
from src.app.integrations.telegram.service import TelegramService
from src.app.memory.conversation_memory import ConversationMemoryService
from src.app.llm.factory import get_llm_provider
from src.app.agents.calendar_agent import CalendarAgent
from src.app.services.calendar_service import CalendarService
from src.app.database.session import AsyncSessionLocal
from src.app.core.logging import logger


def get_orchestrator_dependency() -> AIOrchestrator:
    """FastAPI dependency for obtaining AIOrchestrator instance with full CalendarService injection."""
    llm_provider = get_llm_provider()

    # Build CalendarAgent with a real CalendarService (provider + session_factory for HITL persistence)
    calendar_agent: CalendarAgent | None = None
    try:
        from src.app.integrations.google_calendar.factory import get_calendar_provider
        provider = get_calendar_provider()
        if provider is not None:
            calendar_service = CalendarService(
                provider=provider,
                session_factory=AsyncSessionLocal,
            )
            calendar_agent = CalendarAgent(
                calendar_service=calendar_service,
                llm_provider=llm_provider,
            )
            logger.info("CalendarAgent successfully initialized with provider %s", type(provider).__name__)
        else:
            logger.warning("Calendar provider factory returned None; CalendarAgent initialized without CalendarService.")
            calendar_agent = CalendarAgent(
                calendar_service=None,
                llm_provider=llm_provider,
            )
    except Exception as exc:
        logger.error(
            "CalendarAgent could not be fully initialized in dependency injection (%s: %s)",
            type(exc).__name__,
            exc,
        )
        calendar_agent = CalendarAgent(
            calendar_service=None,
            llm_provider=llm_provider,
        )

    return AIOrchestrator(
        llm_provider=llm_provider,
        calendar_agent=calendar_agent,
    )


def get_telegram_service_dependency() -> TelegramService:
    """FastAPI dependency for obtaining TelegramService instance."""
    return TelegramService()


def get_conversation_memory_service_dependency() -> ConversationMemoryService:
    """FastAPI dependency for obtaining ConversationMemoryService instance."""
    return ConversationMemoryService()

