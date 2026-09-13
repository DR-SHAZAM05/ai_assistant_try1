import pytest

from src.app.core.config import settings
from src.app.core.exceptions import ConfigurationException
from src.app.integrations.telegram.service import TelegramService
from src.app.rag.embeddings import get_embedding_provider


def test_openai_embedding_configuration_cannot_fall_back_to_mock_in_production(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "ALLOW_MOCK_PROVIDERS", True)
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)

    with pytest.raises(ConfigurationException, match="OPENAI_API_KEY"):
        get_embedding_provider()


@pytest.mark.asyncio
async def test_telegram_configuration_cannot_report_a_mock_success_in_production(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", None)

    with pytest.raises(ConfigurationException, match="TELEGRAM_BOT_TOKEN"):
        await TelegramService().send_message(123, "test")


@pytest.mark.asyncio
async def test_webhook_configuration_never_reports_mock_success_for_an_invalid_token(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "ALLOW_MOCK_PROVIDERS", True)

    with pytest.raises(ConfigurationException, match="valid TELEGRAM_BOT_TOKEN"):
        await TelegramService(bot_token="not-a-bot-token").set_webhook(
            "https://example.invalid/telegram/webhook"
        )


def test_malformed_telegram_token_is_not_treated_as_configured(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "not-a-bot-token")

    assert settings.has_valid_telegram_bot_token is False
    assert TelegramService()._has_valid_token is False


def test_production_validation_rejects_a_placeholder_telegram_webhook_secret(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "configured-token")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "your-telegram-webhook-secret-here")

    errors = settings.production_validation_errors()

    assert any("TELEGRAM_WEBHOOK_SECRET" in error for error in errors)


def test_production_validation_requires_telegram_allow_list_and_https_webhook(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "configured-token")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "a" * 32)
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USER_IDS", "")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_URL", "http://localhost:8000/api/v1/telegram/webhook")

    errors = settings.production_validation_errors()

    assert any("TELEGRAM_ALLOWED_USER_IDS" in error for error in errors)
    assert any("TELEGRAM_WEBHOOK_URL" in error for error in errors)


def test_effective_database_url_encodes_a_password_when_explicit_url_is_empty(monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", "")
    monkeypatch.setattr(settings, "POSTGRES_USER", "user")
    monkeypatch.setattr(settings, "POSTGRES_PASSWORD", "password@with:reserved/characters")
    monkeypatch.setattr(settings, "POSTGRES_DB", "assistant")

    assert "password%40with%3Areserved%2Fcharacters" in settings.effective_database_url
