from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from src.app.core.config import settings
from src.app.core.logging import logger

# Create async engine for PostgreSQL
engine = create_async_engine(
    settings.effective_database_url,
    echo=settings.SQL_ECHO,
    future=True,
    connect_args={"timeout": settings.DATABASE_CONNECT_TIMEOUT_SECONDS},
)

# Async session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)


async def get_db_session():
    """
    FastAPI dependency for yielding asynchronous SQLAlchemy database sessions.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as exc:
            await session.rollback()
            logger.error("Database session failed (%s).", type(exc).__name__)
            raise
        finally:
            await session.close()
