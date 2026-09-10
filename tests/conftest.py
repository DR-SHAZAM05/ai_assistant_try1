"""Keep automated tests isolated from credentials and external side effects."""

import os


# pytest imports this module before application modules.  Explicit values here
# ensure a developer's populated .env cannot trigger live provider calls.
os.environ["APP_ENV"] = "test"
os.environ["ALLOW_MOCK_PROVIDERS"] = "true"
os.environ["LLM_PROVIDER"] = "openai"
os.environ["DEFAULT_MODEL"] = "test-model"
os.environ["OPENAI_API_KEY"] = "your-openai-api-key"
os.environ["EMAIL_PROVIDER"] = "mock"
os.environ["UNITBV_EMAIL_PROVIDER"] = "mock"
os.environ["CALENDAR_PROVIDER"] = "mock"
os.environ["EMBEDDING_PROVIDER"] = "mock"
os.environ["EMBEDDING_MODEL"] = "test-embedding-model"
os.environ["EMBEDDING_VECTOR_SIZE"] = "1536"
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_WEBHOOK_SECRET"] = ""
os.environ["TELEGRAM_ALLOWED_USER_IDS"] = ""
os.environ["QDRANT_HOST"] = "127.0.0.1"
os.environ["QDRANT_URL"] = "http://127.0.0.1:1"
os.environ["QDRANT_API_KEY"] = ""
os.environ["QDRANT_COLLECTION"] = "practice_knowledge_test"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@127.0.0.1:1/test"
os.environ["DATABASE_CONNECT_TIMEOUT_SECONDS"] = "0.05"
os.environ["EXTERNAL_RETRY_ATTEMPTS"] = "1"
os.environ["EXTERNAL_REQUEST_TIMEOUT_SECONDS"] = "0.1"
