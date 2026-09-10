from fastapi.testclient import TestClient

from src.app.core.config import settings
from src.app.main import app


def test_automation_endpoints_require_a_configured_key(monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_API_KEY", "test-automation-key")
    client = TestClient(app)

    response = client.post("/api/v1/automation/email/poll")

    assert response.status_code == 401


def test_mailbox_poll_uses_the_internal_credential(monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_API_KEY", "test-automation-key")
    client = TestClient(app)

    response = client.post(
        "/api/v1/automation/email/poll",
        headers={"x-automation-key": "test-automation-key"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_news_refresh_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_API_KEY", "test-automation-key")
    client = TestClient(app)

    # Test without auth
    res_unauth = client.post("/api/v1/automation/news/refresh")
    assert res_unauth.status_code == 401

    # Test with auth
    res_auth = client.post(
        "/api/v1/automation/news/refresh",
        headers={"x-automation-key": "test-automation-key"},
    )
    assert res_auth.status_code == 200
    assert res_auth.json()["status"] == "success"


def test_practice_deadlines_check_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_API_KEY", "test-automation-key")
    client = TestClient(app)

    # Test without auth
    res_unauth = client.post("/api/v1/automation/practice/deadlines-check")
    assert res_unauth.status_code == 401

    # Test with auth
    res_auth = client.post(
        "/api/v1/automation/practice/deadlines-check",
        headers={"x-automation-key": "test-automation-key"},
        params={"notify_telegram": False},
    )
    assert res_auth.status_code == 200
    assert res_auth.json()["status"] == "success"
    assert "open_action_items" in res_auth.json()


def test_daily_briefing_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_API_KEY", "test-automation-key")
    client = TestClient(app)

    # Test without auth
    res_unauth = client.post("/api/v1/automation/daily-briefing")
    assert res_unauth.status_code == 401

    # Test with auth
    res_auth = client.post(
        "/api/v1/automation/daily-briefing",
        headers={"x-automation-key": "test-automation-key"},
        params={"notify_telegram": False},
    )
    assert res_auth.status_code == 200
    assert res_auth.json()["status"] == "success"
    assert "briefing_length" in res_auth.json()


def test_mailbox_poll_with_telegram_alert(monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_API_KEY", "test-automation-key")
    client = TestClient(app)

    response = client.post(
        "/api/v1/automation/email/poll",
        headers={"x-automation-key": "test-automation-key"},
        params={"notify_telegram": False},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["success", "partial"]
    assert "urgent_detected" in data

