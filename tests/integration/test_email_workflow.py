import pytest
from fastapi.testclient import TestClient
from src.app.main import app

from src.app.core.config import settings

client = TestClient(app)


@pytest.fixture(autouse=True)
def configure_test_env(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USER_IDS", "")
    if settings.TELEGRAM_WEBHOOK_SECRET:
        client.headers.update({"x-telegram-bot-api-secret-token": settings.TELEGRAM_WEBHOOK_SECRET})
    yield
    client.headers.pop("x-telegram-bot-api-secret-token", None)


def test_scenario_1_unitbv_important_emails():
    """TEST 1: User asks for important UNITBV emails."""
    payload = {
        "update_id": 200001,
        "message": {
            "message_id": 101,
            "date": 1700000000,
            "chat": {"id": 111111, "type": "private", "first_name": "Student1"},
            "from": {"id": 111111, "is_bot": False, "first_name": "Student1"},
            "text": "Arată-mi mailurile importante primite astăzi pe UNITBV."
        }
    }
    res = client.post("/api/v1/telegram/webhook", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["intent"] in ["email_query", "email_search"]
    assert "UNITBV" in data["response_summary"]


def test_scenario_2_personal_emails():
    """TEST 2: User asks for personal emails."""
    payload = {
        "update_id": 200002,
        "message": {
            "message_id": 102,
            "date": 1700000000,
            "chat": {"id": 222222, "type": "private", "first_name": "Student2"},
            "from": {"id": 222222, "is_bot": False, "first_name": "Student2"},
            "text": "Arată-mi mailurile primite astăzi pe contul personal."
        }
    }
    res = client.post("/api/v1/telegram/webhook", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert "PERSONAL" in data["response_summary"]


def test_scenario_3_action_items():
    """TEST 3: User asks for email action items."""
    payload = {
        "update_id": 200003,
        "message": {
            "message_id": 103,
            "date": 1700000000,
            "chat": {"id": 333333, "type": "private", "first_name": "Student3"},
            "from": {"id": 333333, "is_bot": False, "first_name": "Student3"},
            "text": "Ce trebuie să fac din mailurile primite?"
        }
    }
    res = client.post("/api/v1/telegram/webhook", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["intent"] == "email_action_items"


def test_scenario_4_5_6_draft_and_human_approval_flow():
    """TEST 4, 5, 6: Draft generation, Rejection (Nu), Approval (Da)."""
    chat_id = 444444

    # TEST 4: Generate Draft
    draft_payload = {
        "update_id": 200004,
        "message": {
            "message_id": 104,
            "date": 1700000000,
            "chat": {"id": chat_id, "type": "private", "first_name": "Student4"},
            "from": {"id": chat_id, "is_bot": False, "first_name": "Student4"},
            "text": "Răspunde la acest mail."
        }
    }
    res1 = client.post("/api/v1/telegram/webhook", json=draft_payload)
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["intent"] == "email_draft_reply"
    assert "draft" in data1["response_summary"].lower()

    # TEST 5: Reject sending ("Nu")
    reject_payload = {
        "update_id": 200005,
        "message": {
            "message_id": 105,
            "date": 1700000000,
            "chat": {"id": chat_id, "type": "private", "first_name": "Student4"},
            "from": {"id": chat_id, "is_bot": False, "first_name": "Student4"},
            "text": "Nu."
        }
    }
    res2 = client.post("/api/v1/telegram/webhook", json=reject_payload)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["intent"] == "email_send_confirmation"
    assert "anulată" in data2["response_summary"].lower()

    # Generate draft again for approval test
    client.post("/api/v1/telegram/webhook", json=draft_payload)

    # TEST 6: Approve sending ("Da")
    approve_payload = {
        "update_id": 200006,
        "message": {
            "message_id": 106,
            "date": 1700000000,
            "chat": {"id": chat_id, "type": "private", "first_name": "Student4"},
            "from": {"id": chat_id, "is_bot": False, "first_name": "Student4"},
            "text": "Da."
        }
    }
    res3 = client.post("/api/v1/telegram/webhook", json=approve_payload)
    assert res3.status_code == 200
    data3 = res3.json()
    assert data3["intent"] == "email_send_confirmation"
    assert "succes" in data3["response_summary"].lower() or "trimis" in data3["response_summary"].lower()
