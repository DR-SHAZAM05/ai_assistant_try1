from fastapi.testclient import TestClient

from src.app.main import app


client = TestClient(app)


def test_m5_unitbv_practice_email_draft_and_approval_flow():
    chat_id = 555555

    draft_payload = {
        "update_id": 500001,
        "message": {
            "message_id": 501,
            "date": 1700000000,
            "chat": {"id": chat_id, "type": "private", "first_name": "StudentM5"},
            "from": {"id": chat_id, "is_bot": False, "first_name": "StudentM5"},
            "text": "Răspunde la mailul de practică de pe UNITBV folosind ghidul oficial."
        }
    }
    draft_response = client.post("/api/v1/telegram/webhook", json=draft_payload)
    assert draft_response.status_code == 200
    draft_data = draft_response.json()
    assert draft_data["status"] == "success"
    assert draft_data["intent"] == "email_draft_reply"
    assert "draft" in draft_data["response_summary"].lower()

    approve_payload = {
        "update_id": 500002,
        "message": {
            "message_id": 502,
            "date": 1700000000,
            "chat": {"id": chat_id, "type": "private", "first_name": "StudentM5"},
            "from": {"id": chat_id, "is_bot": False, "first_name": "StudentM5"},
            "text": "Da."
        }
    }
    approval_response = client.post("/api/v1/telegram/webhook", json=approve_payload)
    assert approval_response.status_code == 200
    approval_data = approval_response.json()
    assert approval_data["status"] == "success"
    assert approval_data["intent"] == "email_send_confirmation"
    assert "trimis" in approval_data["response_summary"].lower() or "succes" in approval_data["response_summary"].lower()


def test_m5_unitbv_practice_email_rejection_flow():
    chat_id = 555556

    draft_payload = {
        "update_id": 500003,
        "message": {
            "message_id": 503,
            "date": 1700000000,
            "chat": {"id": chat_id, "type": "private", "first_name": "StudentM5Reject"},
            "from": {"id": chat_id, "is_bot": False, "first_name": "StudentM5Reject"},
            "text": "Răspunde la mailul de practică despre convenție."
        }
    }
    draft_response = client.post("/api/v1/telegram/webhook", json=draft_payload)
    assert draft_response.status_code == 200
    draft_data = draft_response.json()
    assert draft_data["intent"] == "email_draft_reply"

    reject_payload = {
        "update_id": 500004,
        "message": {
            "message_id": 504,
            "date": 1700000000,
            "chat": {"id": chat_id, "type": "private", "first_name": "StudentM5Reject"},
            "from": {"id": chat_id, "is_bot": False, "first_name": "StudentM5Reject"},
            "text": "Nu."
        }
    }
    reject_response = client.post("/api/v1/telegram/webhook", json=reject_payload)
    assert reject_response.status_code == 200
    reject_data = reject_response.json()
    assert reject_data["intent"] == "email_send_confirmation"
    assert "anulat" in reject_data["response_summary"].lower() or "nu" in reject_data["response_summary"].lower()


def test_m5_unitbv_practice_colocviu_draft_flow():
    chat_id = 555557

    draft_payload = {
        "update_id": 500005,
        "message": {
            "message_id": 505,
            "date": 1700000000,
            "chat": {"id": chat_id, "type": "private", "first_name": "StudentColocviu"},
            "from": {"id": chat_id, "is_bot": False, "first_name": "StudentColocviu"},
            "text": "Compune răspuns la mailul despre colocviu de practică."
        }
    }
    draft_response = client.post("/api/v1/telegram/webhook", json=draft_payload)
    assert draft_response.status_code == 200
    draft_data = draft_response.json()
    assert draft_data["intent"] == "email_draft_reply"
    assert "draft" in draft_data["response_summary"].lower()
