from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import delete, select, text

from src.app.core.logging import logger
from src.app.core.config import settings
from src.app.core.exceptions import PersistenceException
from src.app.core.user_scope import require_user_id
from src.app.database.models.models import Conversation, ConversationMessage
from src.app.database.session import AsyncSessionLocal, engine


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


_memory_conversation_store: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}


class ConversationMemoryService:
    """
    Manages short-term multi-turn conversation memory for Telegram sessions.
    Backed by PostgreSQL (conversations & conversation_messages), with in-memory fallback.
    """

    def __init__(self, session_factory=AsyncSessionLocal, database_engine=engine):
        self.session_factory = session_factory
        self.database_engine = database_engine
        self._schema_ready = False
        self._db_available = True

    async def add_message(
        self,
        session_id: str,
        sender_role: str,
        content: str,
        telegram_chat_id: Optional[str] = None,
        tool_calls: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        owner_id = require_user_id(user_id)
        normalized_session_id = self._require_session_id(session_id)
        chat_id = str(telegram_chat_id or normalized_session_id)
        entry = {
            "role": sender_role,
            "content": content,
            "tool_calls": tool_calls,
            "created_at": _utcnow_naive(),
        }

        if not await self._can_use_database():
            _memory_conversation_store.setdefault(owner_id, {}).setdefault(normalized_session_id, []).append(entry)
            return

        try:
            async with self.session_factory() as session:
                # Find or create conversation
                stmt = select(Conversation).where(
                    Conversation.user_id == owner_id,
                    Conversation.session_id == normalized_session_id,
                )
                res = await session.execute(stmt)
                conv = res.scalar_one_or_none()

                if not conv:
                    conv = Conversation(
                        user_id=owner_id,
                        session_id=normalized_session_id,
                        telegram_chat_id=chat_id,
                        created_at=_utcnow_naive(),
                    )
                    session.add(conv)
                    await session.flush()

                msg = ConversationMessage(
                    conversation_id=conv.id,
                    sender_role=sender_role,
                    content=content,
                    tool_calls=tool_calls,
                    created_at=_utcnow_naive(),
                )
                session.add(msg)
                await session.commit()
                _memory_conversation_store.setdefault(owner_id, {}).setdefault(normalized_session_id, []).append(entry)
        except Exception as exc:
            self._disable_database(exc)
            _memory_conversation_store.setdefault(owner_id, {}).setdefault(normalized_session_id, []).append(entry)

    async def get_history(
        self,
        session_id: str,
        limit: int = 10,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """
        Returns recent messages formatted as [{"role": "user"|"assistant", "content": "..."}]
        suitable for passing to LLM context.
        """
        owner_id = require_user_id(user_id)
        normalized_session_id = self._require_session_id(session_id)
        if await self._can_use_database():
            try:
                async with self.session_factory() as session:
                    stmt = (
                        select(ConversationMessage)
                        .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
                        .where(
                            Conversation.user_id == owner_id,
                            Conversation.session_id == normalized_session_id,
                        )
                        .order_by(ConversationMessage.id.desc())
                        .limit(limit)
                    )
                    res = await session.execute(stmt)
                    rows = list(reversed(res.scalars().all()))
                    return [{"role": r.sender_role, "content": r.content} for r in rows]
            except Exception as exc:
                self._disable_database(exc)

        mem = _memory_conversation_store.get(owner_id, {}).get(normalized_session_id, [])
        return [{"role": m["role"], "content": m["content"]} for m in mem[-limit:]]

    async def clear_history(self, session_id: str, user_id: Optional[str] = None) -> None:
        owner_id = require_user_id(user_id)
        normalized_session_id = self._require_session_id(session_id)
        _memory_conversation_store.get(owner_id, {}).pop(normalized_session_id, None)
        if not await self._can_use_database():
            return
        try:
            async with self.session_factory() as session:
                await session.execute(
                    delete(Conversation).where(
                        Conversation.user_id == owner_id,
                        Conversation.session_id == normalized_session_id,
                    )
                )
                await session.commit()
        except Exception as exc:
            self._disable_database(exc)

    @staticmethod
    def _require_session_id(session_id: str) -> str:
        normalized = str(session_id or "").strip()
        if not normalized or len(normalized) > 64:
            raise PersistenceException("Conversation session id must contain 1 to 64 characters")
        return normalized

    async def _can_use_database(self) -> bool:
        if not self._db_available:
            if not settings.persistence_fallback_allowed:
                raise PersistenceException("Conversation memory database is unavailable")
            return False
        if self._schema_ready:
            return True

        try:
            async with self.database_engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            self._schema_ready = True
            return True
        except Exception as exc:
            self._disable_database(exc)
            return False

    def _disable_database(self, exc: Exception) -> None:
        if self._db_available:
            logger.warning(f"Conversation database unavailable; using memory fallback ({exc}).")
        self._db_available = False
        if not settings.persistence_fallback_allowed:
            raise PersistenceException(f"Conversation memory database is unavailable: {exc}") from exc
