"""Unit tests for MicrosoftGraphEmailProvider and Microsoft 365 email integration."""

import asyncio
from datetime import datetime, timezone
import pytest
import httpx

from src.app.core.config import settings
from src.app.core.exceptions import ConfigurationException, IntegrationException
from src.app.integrations.email.factory import get_email_provider
from src.app.integrations.email.graph_provider import MicrosoftGraphEmailProvider
from src.app.schemas.email import EmailDraftReply, EmailFilterParams, EmailMessageSchema
from src.app.services.email_service import EmailService
from src.app.services.pending_email_draft_store import PendingEmailDraftStore


@pytest.fixture
def graph_settings(monkeypatch):
    """Configure test settings for Microsoft Graph."""
    monkeypatch.setattr(settings, "MICROSOFT_GRAPH_ENDPOINT", "https://graph.microsoft.com/v1.0")
    monkeypatch.setattr(settings, "MICROSOFT_TENANT_ID", "test-tenant-uuid-1234")
    monkeypatch.setattr(settings, "MICROSOFT_CLIENT_ID", "test-client-id-5678")
    monkeypatch.setattr(settings, "MICROSOFT_CLIENT_SECRET", "test-client-secret-safe")
    monkeypatch.setattr(settings, "MICROSOFT_MAILBOX_ADDRESS", "student@unitbv.ro")
    monkeypatch.setattr(settings, "MICROSOFT_SCOPES", "https://graph.microsoft.com/.default")
    monkeypatch.setattr(settings, "MICROSOFT_ACCESS_TOKEN", None)
    monkeypatch.setattr(settings, "UNITBV_EMAIL_PROVIDER", "graph")
    monkeypatch.setattr(settings, "EXTERNAL_RETRY_ATTEMPTS", 2)
    monkeypatch.setattr(settings, "EXTERNAL_REQUEST_TIMEOUT_SECONDS", 5.0)


def test_graph_provider_configuration_detection(graph_settings, monkeypatch):
    """Test _is_configured logic under different configuration states."""
    provider = MicrosoftGraphEmailProvider()
    assert provider._is_configured() is True

    # Missing mailbox address
    monkeypatch.setattr(settings, "MICROSOFT_MAILBOX_ADDRESS", None)
    monkeypatch.setattr(settings, "UNITBV_EMAIL_ACCOUNT", None)
    provider_no_box = MicrosoftGraphEmailProvider()
    assert provider_no_box._is_configured() is False

    # Placeholder secret
    monkeypatch.setattr(settings, "MICROSOFT_MAILBOX_ADDRESS", "student@unitbv.ro")
    monkeypatch.setattr(settings, "MICROSOFT_CLIENT_SECRET", "<YOUR_CLIENT_SECRET>")
    provider_placeholder = MicrosoftGraphEmailProvider()
    assert provider_placeholder._is_configured() is False

    # Static token override
    monkeypatch.setattr(settings, "MICROSOFT_CLIENT_SECRET", None)
    monkeypatch.setattr(settings, "MICROSOFT_ACCESS_TOKEN", "valid-static-bearer-token")
    provider_static = MicrosoftGraphEmailProvider()
    assert provider_static._is_configured() is True


def test_graph_provider_require_configuration_raises(monkeypatch):
    """Test _require_configuration raises ConfigurationException when missing credentials."""
    monkeypatch.setattr(settings, "MICROSOFT_CLIENT_ID", None)
    monkeypatch.setattr(settings, "MICROSOFT_CLIENT_SECRET", None)
    monkeypatch.setattr(settings, "MICROSOFT_ACCESS_TOKEN", None)
    provider = MicrosoftGraphEmailProvider()
    with pytest.raises(ConfigurationException, match="Microsoft Graph settings"):
        provider._require_configuration()


@pytest.mark.asyncio
async def test_graph_provider_token_acquisition_and_caching(graph_settings, monkeypatch):
    """Test OAuth2 token acquisition and proactive caching."""
    provider = MicrosoftGraphEmailProvider()

    token_call_count = 0

    async def mock_post(client_self, url, *args, **kwargs):
        nonlocal token_call_count
        token_call_count += 1
        return httpx.Response(
            status_code=200,
            json={"access_token": "bearer-token-12345", "expires_in": 3600, "token_type": "Bearer"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    token1 = await provider._get_access_token()
    assert token1 == "bearer-token-12345"
    assert token_call_count == 1

    # Second call uses cache, no network hit
    token2 = await provider._get_access_token()
    assert token2 == "bearer-token-12345"
    assert token_call_count == 1


@pytest.mark.asyncio
async def test_graph_provider_token_failure_redacts_credentials(graph_settings, monkeypatch):
    """Test that token acquisition failure raises IntegrationException without leaking secret."""
    provider = MicrosoftGraphEmailProvider()

    async def mock_post(client_self, url, *args, **kwargs):
        return httpx.Response(
            status_code=401,
            json={"error": "invalid_client", "error_description": "Bad client credentials"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    with pytest.raises(IntegrationException) as exc_info:
        await provider._get_access_token()

    err_text = str(exc_info.value)
    assert "HTTP 401" in err_text
    assert "Bad client credentials" in err_text
    # Secret must never appear in error message
    assert "test-client-secret-safe" not in err_text


@pytest.mark.asyncio
async def test_graph_provider_fetch_emails(graph_settings, monkeypatch):
    """Test fetching and parsing messages from Microsoft Graph API."""
    provider = MicrosoftGraphEmailProvider()
    monkeypatch.setattr(provider, "_get_access_token", lambda: asyncio.sleep(0, result="test-token"))

    graph_response = {
        "value": [
            {
                "id": "graph-msg-001",
                "subject": "Convenție de practică 2026",
                "bodyPreview": "Vă rugăm să transmiteți convenția de practică semnată până la 28 august 2026.",
                "body": {
                    "contentType": "html",
                    "content": "<p>Vă rugăm să transmiteți <b>convenția de practică</b> semnată până la 28 august 2026.</p>",
                },
                "from": {
                    "emailAddress": {
                        "name": "Secretariat FIESC",
                        "address": "secretariat.fiesc@unitbv.ro",
                    }
                },
                "toRecipients": [
                    {"emailAddress": {"address": "student@unitbv.ro"}}
                ],
                "receivedDateTime": "2026-08-15T09:30:00Z",
                "importance": "high",
                "isRead": False,
            },
            {
                "id": "graph-msg-002",
                "subject": "Anunț general secretariat",
                "bodyPreview": "Secretariatul va fi deschis între orele 10-14.",
                "body": {
                    "contentType": "text",
                    "content": "Secretariatul va fi deschis între orele 10-14.",
                },
                "from": {
                    "emailAddress": {
                        "name": "Secretariat",
                        "address": "secretariat@unitbv.ro",
                    }
                },
                "toRecipients": [
                    {"emailAddress": {"address": "student@unitbv.ro"}}
                ],
                "receivedDateTime": "2026-08-16T11:00:00Z",
                "importance": "normal",
                "isRead": True,
            }
        ]
    }

    async def mock_request(client_self, method, url, *args, **kwargs):
        assert method == "GET"
        assert "/mailFolders/inbox/messages" in url
        return httpx.Response(
            status_code=200,
            json=graph_response,
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", mock_request)

    emails = await provider.fetch_emails("unitbv")
    assert len(emails) == 2
    assert emails[0].message_id == "graph-msg-001"
    assert "Secretariat FIESC" in emails[0].sender
    assert emails[0].importance == "high"
    assert emails[0].is_practice_related is True
    assert emails[0].detected_deadline == "28 august 2026"
    assert emails[0].requires_action is True
    # Verify HTML tags were stripped from body
    assert "<b>" not in emails[0].body_text
    assert "convenția de practică" in emails[0].body_text

    assert emails[1].message_id == "graph-msg-002"
    assert emails[1].importance == "medium"


@pytest.mark.asyncio
async def test_graph_provider_get_email_by_id(graph_settings, monkeypatch):
    """Test retrieving single email by ID (found and 404)."""
    provider = MicrosoftGraphEmailProvider()
    monkeypatch.setattr(provider, "_get_access_token", lambda: asyncio.sleep(0, result="test-token"))

    async def mock_request(client_self, method, url, *args, **kwargs):
        if "msg-existing" in url:
            return httpx.Response(
                status_code=200,
                json={
                    "id": "msg-existing",
                    "subject": "Subiect Test",
                    "body": {"contentType": "text", "content": "Conținut"},
                    "from": {"emailAddress": {"address": "sender@unitbv.ro"}},
                    "toRecipients": [],
                    "receivedDateTime": "2026-08-10T10:00:00Z",
                },
                request=httpx.Request(method, url),
            )
        return httpx.Response(status_code=404, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", mock_request)

    found = await provider.get_email_by_id("unitbv", "msg-existing")
    assert found is not None
    assert found.message_id == "msg-existing"

    missing = await provider.get_email_by_id("unitbv", "msg-missing")
    assert missing is None


@pytest.mark.asyncio
async def test_graph_provider_send_email(graph_settings, monkeypatch):
    """Test sending an email via Graph sendMail endpoint."""
    provider = MicrosoftGraphEmailProvider()
    monkeypatch.setattr(provider, "_get_access_token", lambda: asyncio.sleep(0, result="test-token"))

    captured_payload = {}

    async def mock_request(client_self, method, url, *args, **kwargs):
        nonlocal captured_payload
        captured_payload = kwargs.get("json_data", kwargs.get("json", {}))
        return httpx.Response(
            status_code=202,
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", mock_request)

    draft = EmailDraftReply(
        draft_id="draft-001",
        original_message_id="graph-msg-001",
        account_type="unitbv",
        recipient="profesor@unitbv.ro",
        subject="Re: Convenție",
        body="Bună ziua,\nAm atașat convenția.\nCu stimă,",
    )

    sent = await provider.send_email("unitbv", draft)
    assert sent is True
    assert captured_payload["message"]["subject"] == "Re: Convenție"
    assert captured_payload["message"]["toRecipients"][0]["emailAddress"]["address"] == "profesor@unitbv.ro"
    assert "Bună ziua" in captured_payload["message"]["body"]["content"]
    assert captured_payload["saveToSentItems"] is True


@pytest.mark.asyncio
async def test_graph_provider_throttling_retry(graph_settings, monkeypatch):
    """Test that HTTP 429 throttling triggers backoff retry and succeeds."""
    provider = MicrosoftGraphEmailProvider()
    monkeypatch.setattr(provider, "_get_access_token", lambda: asyncio.sleep(0, result="test-token"))

    attempts = 0

    async def mock_request(client_self, method, url, *args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                status_code=429,
                headers={"Retry-After": "0.1"},
                request=httpx.Request(method, url),
            )
        return httpx.Response(
            status_code=200,
            json={"value": []},
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", mock_request)

    emails = await provider.fetch_emails("unitbv")
    assert emails == []
    assert attempts == 2


def test_factory_returns_graph_provider_when_configured(graph_settings):
    """Test EmailProviderFactory instantiates UnitbvGraphProvider when configured."""
    from src.app.integrations.email.unitbv_graph_provider import UnitbvGraphProvider
    provider = get_email_provider("unitbv")
    assert isinstance(provider, UnitbvGraphProvider)
    assert provider.account_type == "unitbv"


def test_factory_falls_back_to_mock_in_development_when_unconfigured(monkeypatch):
    """Test factory falls back to MockEmailProvider in dev when Graph credentials missing."""
    monkeypatch.setattr(settings, "UNITBV_EMAIL_PROVIDER", "graph")
    monkeypatch.setattr(settings, "MICROSOFT_CLIENT_ID", None)
    monkeypatch.setattr(settings, "MICROSOFT_CLIENT_SECRET", None)
    monkeypatch.setattr(settings, "MICROSOFT_ACCESS_TOKEN", None)
    monkeypatch.setattr(settings, "ALLOW_MOCK_PROVIDERS", True)
    monkeypatch.setattr(settings, "APP_ENV", "development")

    provider = get_email_provider("unitbv")
    from src.app.integrations.email.mock_provider import MockEmailProvider
    assert isinstance(provider, MockEmailProvider)


def test_factory_raises_in_production_when_unconfigured(monkeypatch):
    """Test factory raises ConfigurationException in production when Graph credentials missing."""
    from src.app.integrations.email.unitbv_graph_provider import UnitbvGraphProvider
    monkeypatch.setattr(settings, "UNITBV_EMAIL_PROVIDER", "graph")
    monkeypatch.setattr(settings, "MICROSOFT_CLIENT_ID", None)
    monkeypatch.setattr(settings, "MICROSOFT_CLIENT_SECRET", None)
    monkeypatch.setattr(settings, "MICROSOFT_ACCESS_TOKEN", None)
    monkeypatch.setattr(settings, "ALLOW_MOCK_PROVIDERS", False)
    monkeypatch.setattr(settings, "APP_ENV", "production")

    provider = get_email_provider("unitbv")
    assert isinstance(provider, UnitbvGraphProvider)
    with pytest.raises(ConfigurationException):
        provider._require_configuration()


@pytest.mark.asyncio
async def test_hitl_approval_flow_with_graph_provider(graph_settings, monkeypatch):
    """Verify end-to-end Human-in-the-Loop workflow with MicrosoftGraphEmailProvider."""
    sent_emails = []

    class FakeGraphProvider(MicrosoftGraphEmailProvider):
        def _is_configured(self):
            return True

        async def get_email_by_id(self, account_type, message_id):
            return EmailMessageSchema(
                message_id=message_id,
                account_type="unitbv",
                sender="profesor@unitbv.ro",
                subject="Subiect Practică",
                body_text="Vă rog să confirmați stagiul de practică.",
                received_at=datetime.now(timezone.utc),
                is_practice_related=True,
            )

        async def send_email(self, account_type, draft):
            sent_emails.append(draft)
            return True

    fake_provider = FakeGraphProvider()
    monkeypatch.setattr("src.app.services.email_service.get_email_provider", lambda acc: fake_provider)

    service = EmailService()
    user_id = "telegram-user-hitl-1"

    # Step 1: Create draft (Status: pending_approval)
    draft = await service.create_reply_draft(
        account_type="unitbv",
        message_id="msg-graph-test-01",
        user_instructions="Confirmă că totul este în regulă.",
        owner_id=user_id,
    )
    assert draft.status == "pending_approval"
    assert len(sent_emails) == 0  # CRITICAL: email not sent yet!

    # Step 2: Rejection cancels draft without sending
    rejection = await service.send_email_after_approval(
        draft_id=draft.draft_id,
        approval_granted=False,
        owner_id=user_id,
    )
    assert rejection["status"] == "cancelled"
    assert len(sent_emails) == 0  # CRITICAL: email still NOT sent!

    # Step 3: Create another draft and approve
    draft2 = await service.create_reply_draft(
        account_type="unitbv",
        message_id="msg-graph-test-01",
        user_instructions="Confirmă stagiul.",
        owner_id=user_id,
    )
    assert draft2.status == "pending_approval"

    # Step 4: Approval sends email via Graph provider
    approval = await service.send_email_after_approval(
        draft_id=draft2.draft_id,
        approval_granted=True,
        owner_id=user_id,
    )
    assert approval["status"] == "sent"
    assert len(sent_emails) == 1
    assert sent_emails[0].recipient == "profesor@unitbv.ro"

    # Step 5: Duplicate approval attempt fails (idempotent / double-click protection)
    duplicate = await service.send_email_after_approval(
        draft_id=draft2.draft_id,
        approval_granted=True,
        owner_id=user_id,
    )
    assert duplicate["status"] == "error"
    assert len(sent_emails) == 1  # Not sent twice!
