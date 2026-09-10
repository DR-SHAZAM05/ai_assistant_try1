from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import asyncio
from pathlib import Path

import httpx
from sqlalchemy import text
from src.app.core.config import is_valid_telegram_bot_token, settings
from src.app.core.exceptions import ConfigurationException
from src.app.core.logging import setup_logging, logger
from src.app.api.routes.telegram import router as telegram_router
from src.app.api.routes.automation import router as automation_router

# Initialize structured logging
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    validation_errors = settings.production_validation_errors()
    if validation_errors:
        raise ConfigurationException("Invalid production configuration: " + "; ".join(validation_errors))
    logger.info("==================================================")
    logger.info(f"Starting Personal Academic AI Assistant v0.1.0")
    logger.info(f"Environment: {settings.APP_ENV}")
    logger.info(f"Academic Year: {settings.CURRENT_ACADEMIC_YEAR}")
    logger.info("==================================================")
    if is_valid_telegram_bot_token(settings.TELEGRAM_BOT_TOKEN):
        try:
            from src.app.integrations.telegram.service import TelegramService
            await TelegramService().set_bot_commands()
            logger.info("Registered official Telegram Bot commands with Telegram Bot API.")
        except Exception as exc:
            logger.warning("Failed to register Telegram Bot commands on startup: %s", exc)
    try:
        yield
    finally:
        from src.app.database.session import engine
        await engine.dispose()
        logger.info("Shutting down Personal Academic AI Assistant.")


app = FastAPI(
    title="Personal Academic AI Assistant API",
    description="Modular AI assistant for Telegram, Email, Google Calendar, Practice Knowledge Base, and News.",
    version="0.1.0",
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    lifespan=lifespan
)

# Development accepts any origin. Production must set explicit origins in .env.
cors_origins = settings.cors_allowed_origins or ([] if settings.is_production else ["*"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=cors_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API v1 Routers
app.include_router(telegram_router, prefix="/api/v1")
app.include_router(automation_router, prefix="/api/v1")


def _uses_ollama() -> bool:
    """Return whether the running configuration depends on the local runtime."""
    return (
        settings.LLM_PROVIDER.lower() == "ollama"
        or settings.EMBEDDING_PROVIDER.lower() == "ollama"
    )


def _normalise_ollama_model_name(name: str) -> str:
    """Ollama reports an omitted tag as ``:latest`` in its model listing."""
    return name.strip().removesuffix(":latest")


async def _postgres_ready() -> bool:
    try:
        from src.app.database.session import engine

        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def _qdrant_ready() -> bool:
    client = None
    try:
        from qdrant_client import AsyncQdrantClient

        client = AsyncQdrantClient(
            url=settings.effective_qdrant_url,
            api_key=settings.QDRANT_API_KEY,
            timeout=3.0,
        )
        await client.get_collections()
        return True
    except Exception:
        return False
    finally:
        if client is not None:
            await client.close()


async def _ollama_ready() -> bool:
    """Check that Ollama responds and contains every model required by this process."""
    if not _uses_ollama():
        return True

    required_models = set()
    if settings.LLM_PROVIDER.lower() == "ollama":
        required_models.add(_normalise_ollama_model_name(settings.OLLAMA_MODEL))
    if settings.EMBEDDING_PROVIDER.lower() == "ollama":
        required_models.add(_normalise_ollama_model_name(settings.EMBEDDING_MODEL))

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/tags")
            response.raise_for_status()
        models = response.json().get("models", [])
        available_models = {
            _normalise_ollama_model_name(str(model.get("name") or model.get("model") or ""))
            for model in models
            if isinstance(model, dict)
        }
        return required_models.issubset(available_models)
    except Exception:
        return False


@app.get("/", tags=["General"])
async def root():
    return {
        "app_name": "Personal Academic AI Assistant",
        "status": "online",
        "version": "0.1.0",
        "academic_year": settings.CURRENT_ACADEMIC_YEAR
    }


@app.get("/health", tags=["General"])
async def health_check():
    return {
        "status": "healthy",
        "environment": settings.APP_ENV,
        "academic_year": settings.CURRENT_ACADEMIC_YEAR,
        "llm_provider": settings.LLM_PROVIDER
    }


@app.get("/health/live", tags=["General"])
async def liveness_check():
    """Container liveness probe; it does not claim external services are ready."""
    return {"status": "live"}


@app.get("/health/ready", tags=["General"])
async def readiness_check():
    """Verify the persistent services required by the active runtime."""
    failures = []
    if not await _postgres_ready():
        logger.warning("Readiness check failed for PostgreSQL.")
        failures.append("postgres")

    if not await _qdrant_ready():
        logger.warning("Readiness check failed for Qdrant.")
        failures.append("qdrant")

    if _uses_ollama() and not await _ollama_ready():
        logger.warning("Readiness check failed for Ollama or a required Ollama model.")
        failures.append("ollama")

    if failures:
        return JSONResponse(status_code=503, content={"status": "not_ready", "failures": failures})
    return {"status": "ready"}


@app.get("/health/dependencies", tags=["General"])
async def dependency_status():
    """Expose credential-free configuration and local runtime state."""
    calendar_configured = (
        bool(settings.GOOGLE_SERVICE_ACCOUNT_FILE and Path(settings.GOOGLE_SERVICE_ACCOUNT_FILE).is_file())
        if settings.GOOGLE_AUTH_MODE == "service_account"
        else bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET and Path(settings.GOOGLE_TOKEN_FILE).is_file())
    )
    integrations = {
        "llm": bool(settings.OPENAI_API_KEY) if settings.LLM_PROVIDER == "openai" else bool(settings.OLLAMA_BASE_URL),
        "embeddings": bool(settings.OPENAI_API_KEY) if settings.EMBEDDING_PROVIDER == "openai" else bool(settings.OLLAMA_BASE_URL),
        "telegram": bool(
            settings.has_valid_telegram_bot_token
            and settings.has_valid_telegram_webhook_secret
            and settings.telegram_allowed_user_ids
            and settings.has_valid_telegram_webhook_url
        ),
        "calendar": calendar_configured,
        "email_personal": bool(settings.EMAIL_ACCOUNT and settings.EMAIL_PASSWORD and settings.EMAIL_IMAP_SERVER),
        "email_unitbv": bool(settings.UNITBV_EMAIL_ACCOUNT and settings.UNITBV_EMAIL_PASSWORD and settings.UNITBV_EMAIL_IMAP_SERVER),
    }
    return {
        "status": "configured" if all(integrations.values()) else "partial",
        "integrations": integrations,
        "runtime": {
            "ollama": {
                "required": _uses_ollama(),
                "reachable": await _ollama_ready() if _uses_ollama() else None,
            }
        },
    }
