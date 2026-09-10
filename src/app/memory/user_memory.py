from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import delete, select, text

from src.app.core.logging import logger
from src.app.core.config import settings
from src.app.core.exceptions import PersistenceException
from src.app.database.models.models import UserMemory
from src.app.database.session import AsyncSessionLocal, engine


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


_memory_user_store: Dict[str, Dict[str, Any]] = {}


class UserMemoryService:
    """
    Manages long-term user memories and preferences.
    Backed by PostgreSQL (user_memories table), with process memory fallback.
    """

    def __init__(self, session_factory=AsyncSessionLocal):
        self.session_factory = session_factory
        self._schema_ready = False
        self._db_available = True

    async def get_memory(self, key: str) -> Optional[str]:
        if await self._can_use_database():
            try:
                async with self.session_factory() as session:
                    stmt = select(UserMemory).where(UserMemory.key == key)
                    res = await session.execute(stmt)
                    item = res.scalar_one_or_none()
                    return item.value if item else None
            except Exception as exc:
                self._disable_database(exc)

        mem = _memory_user_store.get(key)
        return mem["value"] if mem else None

    async def set_memory(self, key: str, value: str, category: Optional[str] = None) -> None:
        entry = {
            "key": key,
            "value": value,
            "category": category,
            "created_at": _utcnow_naive(),
        }
        _memory_user_store[key] = entry

        if not await self._can_use_database():
            return

        try:
            async with self.session_factory() as session:
                stmt = select(UserMemory).where(UserMemory.key == key)
                res = await session.execute(stmt)
                item = res.scalar_one_or_none()

                if item:
                    item.value = value
                    item.category = category
                else:
                    item = UserMemory(key=key, value=value, category=category)
                    session.add(item)

                await session.commit()
        except Exception as exc:
            self._disable_database(exc)

    async def list_memories(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        if await self._can_use_database():
            try:
                async with self.session_factory() as session:
                    stmt = select(UserMemory)
                    if category:
                        stmt = stmt.where(UserMemory.category == category)
                    res = await session.execute(stmt)
                    rows = res.scalars().all()
                    return [{"key": r.key, "value": r.value, "category": r.category} for r in rows]
            except Exception as exc:
                self._disable_database(exc)

        items = list(_memory_user_store.values())
        if category:
            items = [i for i in items if i.get("category") == category]
        return items

    async def delete_memory(self, key: str) -> bool:
        existed_in_mem = key in _memory_user_store
        _memory_user_store.pop(key, None)

        if not await self._can_use_database():
            return existed_in_mem

        try:
            async with self.session_factory() as session:
                stmt = delete(UserMemory).where(UserMemory.key == key)
                res = await session.execute(stmt)
                await session.commit()
                return (res.rowcount or 0) > 0 or existed_in_mem
        except Exception as exc:
            self._disable_database(exc)
            return existed_in_mem

    async def _can_use_database(self) -> bool:
        if not self._db_available:
            if not settings.mocks_allowed:
                raise PersistenceException("User memory database is unavailable")
            return False
        if self._schema_ready:
            return True

        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            self._schema_ready = True
            return True
        except Exception as exc:
            self._disable_database(exc)
            return False

    def _disable_database(self, exc: Exception) -> None:
        if self._db_available:
            logger.warning(f"UserMemory database unavailable; using memory fallback ({exc}).")
        self._db_available = False
        if not settings.mocks_allowed:
            raise PersistenceException(f"User memory database is unavailable: {exc}") from exc
