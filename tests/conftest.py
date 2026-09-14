"""Keep automated tests isolated from credentials and external side effects."""

import os
import sys

# Add /app to the Python path so imports like 'from src...' work
if "/app" not in sys.path:
    sys.path.insert(0, "/app")


# pytest imports this module before application modules.  Explicit values here
# ensure a developer's populated .env cannot trigger live provider calls.
is_live_rag = os.environ.get("RUN_LIVE_RAG", "").lower() in ("1", "true", "yes")

os.environ["APP_ENV"] = "test"
os.environ["LLM_PROVIDER"] = "openai"
os.environ["DEFAULT_MODEL"] = "test-model"
os.environ["OPENAI_API_KEY"] = "your-openai-api-key"
os.environ["EMAIL_PROVIDER"] = "mock"
os.environ["UNITBV_EMAIL_PROVIDER"] = "mock"
os.environ["CALENDAR_PROVIDER"] = "mock"
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_WEBHOOK_SECRET"] = ""
os.environ["TELEGRAM_ALLOWED_USER_IDS"] = ""

if is_live_rag:
    # Live RAG mode: use real Ollama and real Qdrant from environment/.env
    os.environ["ALLOW_MOCK_PROVIDERS"] = "false"
    os.environ.setdefault("EMBEDDING_PROVIDER", "ollama")
    os.environ.setdefault("EMBEDDING_MODEL", "nomic-embed-text")
    os.environ.setdefault("EMBEDDING_VECTOR_SIZE", "768")
    os.environ.setdefault("OLLAMA_BASE_URL", "http://127.0.0.1:11435")
    os.environ.setdefault("QDRANT_HOST", "127.0.0.1")
    os.environ.setdefault("QDRANT_PORT", "6333")
    os.environ.setdefault("QDRANT_URL", "http://127.0.0.1:6333")
    os.environ.setdefault("EXTERNAL_REQUEST_TIMEOUT_SECONDS", "30.0")
else:
    # Standard test mode: fully isolated mocks
    os.environ["ALLOW_MOCK_PROVIDERS"] = "true"
    os.environ["EMBEDDING_PROVIDER"] = "mock"
    os.environ["EMBEDDING_MODEL"] = "test-embedding-model"
    os.environ["EMBEDDING_VECTOR_SIZE"] = "768"
    os.environ["QDRANT_HOST"] = "127.0.0.1"
    os.environ["QDRANT_URL"] = "http://127.0.0.1:1"
    os.environ["QDRANT_API_KEY"] = ""
    os.environ["QDRANT_COLLECTION"] = "practice_knowledge_test"
    os.environ["EXTERNAL_REQUEST_TIMEOUT_SECONDS"] = "0.1"

os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@127.0.0.1:1/test"
os.environ["DATABASE_CONNECT_TIMEOUT_SECONDS"] = "0.05"
os.environ["EXTERNAL_RETRY_ATTEMPTS"] = "1"
