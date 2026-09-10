class AcademicAssistantException(Exception):
    """Base exception for Personal Academic AI Assistant."""
    pass


class ConfigurationException(AcademicAssistantException):
    """Raised when environment settings or options are invalid."""
    pass


class LLMProviderException(AcademicAssistantException):
    """Raised when an LLM provider fails to generate completion."""
    pass


class IntegrationException(AcademicAssistantException):
    """Raised when an external API service (Telegram, Google, Email) fails."""
    pass


class RAGRetrievalException(AcademicAssistantException):
    """Raised when vector DB search or document ingestion fails."""
    pass


class PersistenceException(AcademicAssistantException):
    """Raised when a required persistent data store is unavailable."""
    pass


class HumanApprovalRequiredException(AcademicAssistantException):
    """Raised when an operation requires explicit user confirmation before executing."""
    pass
