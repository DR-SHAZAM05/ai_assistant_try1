from src.app.integrations.google_calendar.base import CalendarProvider
from src.app.integrations.google_calendar.mock_provider import MockCalendarProvider
from src.app.integrations.google_calendar.google_provider import GoogleCalendarProvider
from src.app.core.config import settings
from src.app.core.exceptions import ConfigurationException
from src.app.core.logging import logger
from pathlib import Path

_mock_calendar_instance = MockCalendarProvider()


def get_calendar_provider() -> CalendarProvider:
    """
    Factory function returning the configured CalendarProvider instance.
    Mocks are only available for explicit development/test configuration.
    """
    provider_name = settings.CALENDAR_PROVIDER.lower()

    if provider_name == "google":
        has_credentials = (
            settings.GOOGLE_AUTH_MODE.lower() == "service_account"
            and bool(settings.GOOGLE_SERVICE_ACCOUNT_FILE and Path(settings.GOOGLE_SERVICE_ACCOUNT_FILE).is_file())
        ) or (
            settings.GOOGLE_AUTH_MODE.lower() == "oauth"
            and Path(settings.GOOGLE_TOKEN_FILE).is_file()
        )
        if not has_credentials and settings.mocks_allowed:
            logger.warning("Google Calendar is not authorized; using the development mock provider.")
            return _mock_calendar_instance
        return GoogleCalendarProvider()
    if provider_name == "mock" and settings.mocks_allowed:
        logger.info("Using MockCalendarProvider for calendar operations.")
        return _mock_calendar_instance
    if provider_name == "mock":
        raise ConfigurationException("CALENDAR_PROVIDER=mock is not allowed in production")
    raise ConfigurationException(f"Unsupported calendar provider: {provider_name}")
