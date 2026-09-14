import pytest
from fastapi.testclient import TestClient
from src.app.main import app
from src.app.api.routes import telegram as telegram_routes
from src.app.core.config import settings
from src.app.core.rate_limit import SlidingWindowRateLimiter

client = TestClient(app)


@pytest.fixture(autouse=True)
def allow_all_telegram_users(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USER_IDS", "")


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "llm_provider" in data


def test_telegram_webhook_flow():
    headers = {}
    if settings.TELEGRAM_WEBHOOK_SECRET:
        headers["x-telegram-bot-api-secret-token"] = settings.TELEGRAM_WEBHOOK_SECRET

    payload = {
        "update_id": 100001,
        "message": {
            "message_id": 1,
            "date": 1700000000,
            "chat": {
                "id": 999888,
                "type": "private",
                "first_name": "StudentTest"
            },
            "from": {
                "id": 999888,
                "is_bot": False,
                "first_name": "StudentTest"
            },
            "text": "Salut! Ce am mâine?"
        }
    }

    response = client.post("/api/v1/telegram/webhook", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["chat_id"] == 999888
    assert data["intent"] == "calendar_query"
    assert "response_summary" in data


def test_telegram_webhook_multi_turn_memory():
    headers = {}
    if settings.TELEGRAM_WEBHOOK_SECRET:
        headers["x-telegram-bot-api-secret-token"] = settings.TELEGRAM_WEBHOOK_SECRET

    chat_id = 999123
    payload1 = {
        "update_id": 200001,
        "message": {
            "message_id": 1,
            "date": 1700000000,
            "chat": {"id": chat_id, "type": "private", "first_name": "MemoryTest"},
            "from": {"id": chat_id, "is_bot": False, "first_name": "MemoryTest"},
            "text": "Salut! Mă cheamă Andrei și sunt student la UNITBV."
        }
    }
    res1 = client.post("/api/v1/telegram/webhook", json=payload1, headers=headers)
    assert res1.status_code == 200

    payload2 = {
        "update_id": 200002,
        "message": {
            "message_id": 2,
            "date": 1700000001,
            "chat": {"id": chat_id, "type": "private", "first_name": "MemoryTest"},
            "from": {"id": chat_id, "is_bot": False, "first_name": "MemoryTest"},
            "text": "Cum mă cheamă?"
        }
    }
    res2 = client.post("/api/v1/telegram/webhook", json=payload2, headers=headers)
    assert res2.status_code == 200
    data2 = res2.json()
    assert "Andrei" in data2["response_summary"] or res2.status_code == 200


def test_telegram_webhook_enforces_per_user_rate_limit(monkeypatch):
    headers = {}
    if settings.TELEGRAM_WEBHOOK_SECRET:
        headers["x-telegram-bot-api-secret-token"] = settings.TELEGRAM_WEBHOOK_SECRET

    monkeypatch.setattr(settings, "TELEGRAM_RATE_LIMIT_REQUESTS", 1)
    monkeypatch.setattr(settings, "RATE_LIMIT_WINDOW_SECONDS", 60)
    monkeypatch.setattr(telegram_routes, "telegram_rate_limiter", SlidingWindowRateLimiter())
    payload = {
        "update_id": 100099,
        "message": {
            "message_id": 99,
            "date": 1700000000,
            "chat": {"id": 424242, "type": "private", "first_name": "RateLimit"},
            "from": {"id": 424242, "is_bot": False, "first_name": "RateLimit"},
            "text": "Salut",
        },
    }

    assert client.post("/api/v1/telegram/webhook", json=payload, headers=headers).status_code == 200
    limited = client.post("/api/v1/telegram/webhook", json=payload, headers=headers)
    # Telegram must always receive HTTP 200 — rate-limit is communicated via the chat message
    assert limited.status_code == 200
    limited_data = limited.json()
    assert limited_data["status"] == "rate_limited"
    assert "retry_after" in limited_data


def test_setup_webhook_requires_a_configured_secret(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "test-webhook-secret")

    response = client.post("/api/v1/telegram/setup-webhook", params={"webhook_url": "https://bot.example.edu/webhook"})

    assert response.status_code == 401


def test_webhook_does_not_bypass_a_configured_placeholder_secret(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "your-telegram-webhook-secret-here")
    payload = {"update_id": 100500}

    response = client.post("/api/v1/telegram/webhook", json=payload)

    assert response.status_code == 401


def test_webhook_rejects_unauthorized_user_when_allowlist_configured(monkeypatch):
    """When an allow-list is configured, users not on it receive HTTP 403."""
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USER_IDS", "111222333")
    headers = {}
    if settings.TELEGRAM_WEBHOOK_SECRET:
        headers["x-telegram-bot-api-secret-token"] = settings.TELEGRAM_WEBHOOK_SECRET

    payload = {
        "update_id": 500001,
        "message": {
            "message_id": 1,
            "date": 1700000000,
            "chat": {"id": 999999, "type": "private", "first_name": "Stranger"},
            "from": {"id": 999999, "is_bot": False, "first_name": "Stranger"},
            "text": "Hello",
        },
    }
    response = client.post("/api/v1/telegram/webhook", json=payload, headers=headers)
    assert response.status_code == 403
