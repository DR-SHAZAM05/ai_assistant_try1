import pytest
import unicodedata
from fastapi.testclient import TestClient
from src.app.main import app

client = TestClient(app)


def _without_diacritics(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in normalized if not unicodedata.combining(character))


def test_m4_scenario_1_how_to_do_practice():
    """TEST 1: User asks 'Cum se face practica?'"""
    payload = {
        "update_id": 400001,
        "message": {
            "message_id": 401,
            "date": 1700000000,
            "chat": {"id": 777777, "type": "private", "first_name": "StudentM4"},
            "from": {"id": 777777, "is_bot": False, "first_name": "StudentM4"},
            "text": "Cum se face practica?"
        }
    }
    res = client.post("/api/v1/telegram/webhook", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["intent"] == "practice_query"
    summary = _without_diacritics(data["response_summary"])
    assert "surse" in summary or "practica" in summary


def test_m4_scenario_2_practice_required_documents():
    """TEST 2: User asks 'Care sunt documentele necesare pentru practică?'"""
    payload = {
        "update_id": 400002,
        "message": {
            "message_id": 402,
            "date": 1700000000,
            "chat": {"id": 777777, "type": "private", "first_name": "StudentM4"},
            "from": {"id": 777777, "is_bot": False, "first_name": "StudentM4"},
            "text": "Care sunt documentele necesare pentru practică?"
        }
    }
    res = client.post("/api/v1/telegram/webhook", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["intent"] == "practice_query"


def test_m4_scenario_3_historical_academic_year():
    """TEST 3: User asks 'Care este termenul pentru practica din anul universitar 2025-2026?'"""
    payload = {
        "update_id": 400003,
        "message": {
            "message_id": 403,
            "date": 1700000000,
            "chat": {"id": 777777, "type": "private", "first_name": "StudentM4"},
            "from": {"id": 777777, "is_bot": False, "first_name": "StudentM4"},
            "text": "Care este termenul pentru practica din anul universitar 2025-2026?"
        }
    }
    res = client.post("/api/v1/telegram/webhook", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["intent"] == "practice_query"
    assert "2025-2026" in data["response_summary"]


def test_m4_scenario_4_anti_hallucination():
    """TEST 4: User asks about non-existent procedure XZY."""
    payload = {
        "update_id": 400004,
        "message": {
            "message_id": 404,
            "date": 1700000000,
            "chat": {"id": 777777, "type": "private", "first_name": "StudentM4"},
            "from": {"id": 777777, "is_bot": False, "first_name": "StudentM4"},
            "text": "Care este procedura XZY9999?"
        }
    }
    res = client.post("/api/v1/telegram/webhook", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert "nu am găsit" in data["response_summary"].lower() or "surse" in data["response_summary"].lower()
