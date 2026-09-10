import pytest
from fastapi.testclient import TestClient
from src.app.main import app

client = TestClient(app)


def test_m3_scenario_1_calendar_tomorrow():
    """TEST 1: User asks 'Ce am mâine?'"""
    payload = {
        "update_id": 300001,
        "message": {
            "message_id": 301,
            "date": 1700000000,
            "chat": {"id": 555555, "type": "private", "first_name": "StudentM3"},
            "from": {"id": 555555, "is_bot": False, "first_name": "StudentM3"},
            "text": "Ce am mâine?"
        }
    }
    res = client.post("/api/v1/telegram/webhook", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["intent"] == "calendar_query"
    assert "mâine" in data["response_summary"].lower() or "programul" in data["response_summary"].lower()


def test_m3_scenario_2_calendar_next_week():
    """TEST 2: User asks 'Ce am săptămâna viitoare?'"""
    payload = {
        "update_id": 300002,
        "message": {
            "message_id": 302,
            "date": 1700000000,
            "chat": {"id": 555555, "type": "private", "first_name": "StudentM3"},
            "from": {"id": 555555, "is_bot": False, "first_name": "StudentM3"},
            "text": "Ce am săptămâna viitoare?"
        }
    }
    res = client.post("/api/v1/telegram/webhook", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["intent"] == "calendar_query"
    assert "săptămâna viitoare" in data["response_summary"].lower() or "programul" in data["response_summary"].lower()


def test_m3_scenario_3_news_ai():
    """TEST 3: User asks 'Ce știri importante sunt despre AI?'"""
    payload = {
        "update_id": 300003,
        "message": {
            "message_id": 303,
            "date": 1700000000,
            "chat": {"id": 666666, "type": "private", "first_name": "StudentNews"},
            "from": {"id": 666666, "is_bot": False, "first_name": "StudentNews"},
            "text": "Ce știri importante sunt despre AI?"
        }
    }
    res = client.post("/api/v1/telegram/webhook", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["intent"] == "news_query"
    assert "știri" in data["response_summary"].lower() or "relevante" in data["response_summary"].lower()
