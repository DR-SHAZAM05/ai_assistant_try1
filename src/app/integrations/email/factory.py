from src.app.integrations.email.base import EmailProvider
from src.app.integrations.email.mock_provider import MockEmailProvider
from src.app.integrations.email.imap_provider import IMAPEmailProvider
from src.app.core.config import settings
from src.app.core.exceptions import ConfigurationException
from src.app.core.logging import logger

_mock_instance = MockEmailProvider()


def get_email_provider(account_type: str = "personal") -> EmailProvider:
    """
    Factory function returning the appropriate EmailProvider instance.
    The mock provider is restricted to development/test execution.
    """
    account_type = account_type.lower()
    
    if account_type == "unitbv":
        provider_name = getattr(settings, "UNITBV_EMAIL_PROVIDER", "imap")
    else:
        provider_name = getattr(settings, "EMAIL_PROVIDER", "imap")

    provider_name = (provider_name or "mock").lower()

    if provider_name == "mock" and settings.mocks_allowed:
        return _mock_instance
    if provider_name == "imap":
        provider = IMAPEmailProvider(account_type=account_type)
        if not provider._is_configured() and settings.mocks_allowed:
            logger.warning("Email account '%s' is not configured; using development mock provider.", account_type)
            return _mock_instance
        return provider
    if provider_name == "mock":
        raise ConfigurationException("EMAIL_PROVIDER=mock is not allowed in production")
    raise ConfigurationException(f"Unsupported email provider: {provider_name}")
