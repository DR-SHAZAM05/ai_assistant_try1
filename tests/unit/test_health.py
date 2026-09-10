from fastapi.testclient import TestClient

import src.app.main as main_module
from src.app.core.config import settings


def test_dependency_status_reports_ollama_runtime_without_credentials(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "ollama")

    async def ollama_available():
        return True

    monkeypatch.setattr(main_module, "_ollama_ready", ollama_available)

    response = TestClient(main_module.app).get("/health/dependencies")

    assert response.status_code == 200
    data = response.json()
    assert data["runtime"]["ollama"] == {"required": True, "reachable": True}


def test_readiness_reports_ollama_when_the_active_runtime_is_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "ollama")

    async def available():
        return True

    async def unavailable():
        return False

    monkeypatch.setattr(main_module, "_postgres_ready", available)
    monkeypatch.setattr(main_module, "_qdrant_ready", available)
    monkeypatch.setattr(main_module, "_ollama_ready", unavailable)

    response = TestClient(main_module.app).get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "failures": ["ollama"]}
