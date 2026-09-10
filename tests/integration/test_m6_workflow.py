import pytest
from fastapi.testclient import TestClient
from src.app.main import app

client = TestClient(app)


def test_m6_scenario_1_query_specific_historical_academic_year():
    """User asks about practice rules for 2024-2025 explicitly."""
    payload = {
        "update_id": 600001,
        "message": {
            "message_id": 601,
            "date": 1700000000,
            "chat": {"id": 888888, "type": "private", "first_name": "StudentM6"},
            "from": {"id": 888888, "is_bot": False, "first_name": "StudentM6"},
            "text": "Care a fost termenul pentru depunerea convenției de practică în 2024-2025?"
        }
    }
    res = client.post("/api/v1/telegram/webhook", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["intent"] == "practice_query"
    assert "2024-2025" in data["response_summary"]


def test_m6_scenario_2_historical_answers_query():
    """User asks what was answered last year about Erasmus."""
    payload = {
        "update_id": 600002,
        "message": {
            "message_id": 602,
            "date": 1700000000,
            "chat": {"id": 888888, "type": "private", "first_name": "StudentM6"},
            "from": {"id": 888888, "is_bot": False, "first_name": "StudentM6"},
            "text": "Ce am răspuns anul trecut despre Erasmus?"
        }
    }
    res = client.post("/api/v1/telegram/webhook", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["intent"] == "practice_history_query"
    assert "2025-2026" in data["response_summary"] or "istoric" in data["response_summary"].lower() or "erasmus" in data["response_summary"].lower()
