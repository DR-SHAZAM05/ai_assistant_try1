from src.app.integrations.email.base import EmailProvider
from src.app.integrations.email.mock_provider import MockEmailProvider
from src.app.integrations.email.imap_provider import IMAPEmailProvider
from src.app.integrations.email.graph_provider import MicrosoftGraphEmailProvider
from src.app.integrations.email.unitbv_graph_provider import UnitbvGraphProvider
from src.app.core.config import settings
from src.app.core.exceptions import ConfigurationException
from src.app.core.logging import logger

_mock_instance = MockEmailProvider()


def get_email_provider(account_type: str = "personal") -> EmailProvider:
    """
    Factory function returning the appropriate EmailProvider instance.
    The mock provider is restricted to development/test execution.
    
    account_type:
      - "personal" → uses EMAIL_PROVIDER setting (IMAP or mock)
      - "unitbv" → uses UNITBV_EMAIL_PROVIDER setting (Graph/IMAP) or defaults to UnitbvGraphProvider
    """
    account_type = account_type.lower()
    
    # UNITBV - new cross-tenant OAuth2 Graph provider
    if account_type == "unitbv":
        unitbv_provider_name = getattr(settings, "UNITBV_EMAIL_PROVIDER", "graph")
        unitbv_provider_name = (unitbv_provider_name or "graph").lower()
        
        # Use new UnitbvGraphProvider (delegated access with /me endpoints)
        if unitbv_provider_name in {"graph", "microsoft", "office365", "ms_graph", "microsoft_graph"}:
            provider = UnitbvGraphProvider(account_type=account_type)
            if not provider._is_configured() and settings.mocks_allowed:
                logger.warning(
                    "UNITBV Microsoft Graph email account is not configured. "
                    "Use provider.get_authorization_url() to start authorization; using mock provider for now."
                )
                return _mock_instance
            return provider
        
        # Fallback to IMAP if configured
        if unitbv_provider_name == "imap":
            provider = IMAPEmailProvider(account_type=account_type)
            if not provider._is_configured() and settings.mocks_allowed:
                logger.warning("UNITBV IMAP account is not configured; using development mock provider.")
                return _mock_instance
            return provider
        
        # Unknown provider
        if unitbv_provider_name == "mock" and settings.mocks_allowed:
            return _mock_instance
        if unitbv_provider_name == "mock":
            raise ConfigurationException("EMAIL_PROVIDER=mock is not allowed in production")
        raise ConfigurationException(f"Unsupported UNITBV email provider: {unitbv_provider_name}")
    
    # Personal email account
    else:
        provider_name = getattr(settings, "EMAIL_PROVIDER", "imap")
        provider_name = (provider_name or "imap").lower()
        
        if provider_name == "mock" and settings.mocks_allowed:
            return _mock_instance
        if provider_name in {"graph", "microsoft", "office365", "ms_graph", "microsoft_graph"}:
            graph_provider = MicrosoftGraphEmailProvider(account_type=account_type)
            if not graph_provider._is_configured() and settings.mocks_allowed:
                logger.warning("Microsoft Graph email account '%s' is not configured; using development mock provider.", account_type)
                return _mock_instance
            return graph_provider
        if provider_name == "imap":
            provider = IMAPEmailProvider(account_type=account_type)
            if not provider._is_configured() and settings.mocks_allowed:
                logger.warning("Email account '%s' is not configured; using development mock provider.", account_type)
                return _mock_instance
            return provider
        if provider_name == "mock":
            raise ConfigurationException("EMAIL_PROVIDER=mock is not allowed in production")
        raise ConfigurationException(f"Unsupported email provider: {provider_name}")
