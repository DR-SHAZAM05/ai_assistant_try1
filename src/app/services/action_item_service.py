from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import select, text

from src.app.core.logging import logger
from src.app.core.config import settings
from src.app.core.exceptions import PersistenceException
from src.app.core.user_scope import require_user_id
from src.app.database.models.models import ActionItem, ActionStatusEnum, PriorityEnum
from src.app.database.session import AsyncSessionLocal, engine


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


_memory_action_items: Dict[str, List[Dict[str, Any]]] = {}
_action_item_counter: int = 0


def _next_action_item_id() -> int:
    global _action_item_counter
    _action_item_counter += 1
    return _action_item_counter


class ActionItemService:
    """
    Manages Action Items and Tasks extracted from emails, calendar, and practice questions.
    Backed by PostgreSQL (action_items table), with in-memory fallback.
    """

    def __init__(self, session_factory=AsyncSessionLocal, database_engine=engine):
        self.session_factory = session_factory
        self.database_engine = database_engine
        self._schema_ready = False
        self._db_available = True

    async def create_action_item(
        self,
        title: str,
        source: str,
        deadline: Optional[datetime] = None,
        priority: str = "medium",
        source_reference: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        owner_id = require_user_id(user_id)
        if deadline and getattr(deadline, "tzinfo", None) is not None:
            deadline = deadline.astimezone(timezone.utc).replace(tzinfo=None)

        item_dict = {
            "id": _next_action_item_id(),
            "user_id": owner_id,
            "title": title,
            "source": source,
            "deadline": deadline,
            "priority": priority,
            "status": "open",
            "source_reference": source_reference,
            "created_at": _utcnow_naive(),
        }

        if not await self._can_use_database():
            owner_items = _memory_action_items.setdefault(owner_id, [])
            for m in owner_items:
                if source_reference and m.get("source_reference") == source_reference:
                    m["title"] = title
                    if deadline:
                        m["deadline"] = deadline
                    return m
            owner_items.append(item_dict)
            return item_dict

        try:
            async with self.session_factory() as session:
                if source_reference:
                    stmt = select(ActionItem).where(
                        ActionItem.user_id == owner_id,
                        ActionItem.source_reference == source_reference,
                    )
                    res = await session.execute(stmt)
                    existing = res.scalar_one_or_none()
                    if existing:
                        existing.title = title
                        if deadline:
                            existing.deadline = deadline
                        await session.commit()
                        return self._to_dict(existing)

                p_enum = PriorityEnum.MEDIUM
                if priority.lower() == "high":
                    p_enum = PriorityEnum.HIGH
                elif priority.lower() == "low":
                    p_enum = PriorityEnum.LOW

                ai = ActionItem(
                    user_id=owner_id,
                    title=title,
                    source=source,
                    deadline=deadline,
                    priority=p_enum,
                    status=ActionStatusEnum.OPEN,
                    source_reference=source_reference,
                    created_at=item_dict["created_at"],
                )
                session.add(ai)
                await session.commit()
                item_dict["id"] = ai.id
                _memory_action_items.setdefault(owner_id, []).append(item_dict)
                return item_dict
        except Exception as exc:
            self._disable_database(exc)
            _memory_action_items.setdefault(owner_id, []).append(item_dict)
            return item_dict

    async def list_action_items(
        self,
        status: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        owner_id = require_user_id(user_id)
        if await self._can_use_database():
            try:
                async with self.session_factory() as session:
                    stmt = select(ActionItem).where(ActionItem.user_id == owner_id)
                    if status:
                        try:
                            s_enum = ActionStatusEnum(status.lower())
                            stmt = stmt.where(ActionItem.status == s_enum)
                        except ValueError:
                            stmt = stmt.where(ActionItem.status == status)
                    res = await session.execute(stmt)
                    rows = res.scalars().all()
                    return [self._to_dict(row) for row in rows]
            except Exception as exc:
                self._disable_database(exc)

        items = list(_memory_action_items.get(owner_id, []))
        if status:
            items = [i for i in items if i.get("status") == status]
        return items

    async def update_action_item_status(
        self,
        item_id: int,
        new_status: str,
        user_id: Optional[str] = None,
    ) -> bool:
        owner_id = require_user_id(user_id)
        updated_in_memory = False
        for item in _memory_action_items.get(owner_id, []):
            if item["id"] == item_id:
                item["status"] = new_status
                updated_in_memory = True

        if not await self._can_use_database():
            return updated_in_memory

        try:
            async with self.session_factory() as session:
                stmt = select(ActionItem).where(
                    ActionItem.id == item_id,
                    ActionItem.user_id == owner_id,
                )
                res = await session.execute(stmt)
                item = res.scalar_one_or_none()
                if item:
                    try:
                        item.status = ActionStatusEnum(new_status.lower())
                    except ValueError:
                        item.status = new_status
                    await session.commit()
                    return True
                return False
        except Exception as exc:
            self._disable_database(exc)
            return updated_in_memory

    @staticmethod
    def _to_dict(item: ActionItem) -> Dict[str, Any]:
        return {
            "id": item.id,
            "user_id": item.user_id,
            "title": item.title,
            "source": item.source,
            "deadline": item.deadline,
            "priority": item.priority.value if hasattr(item.priority, "value") else str(item.priority),
            "status": item.status.value if hasattr(item.status, "value") else str(item.status),
            "source_reference": item.source_reference,
            "created_at": item.created_at,
        }

    async def _can_use_database(self) -> bool:
        if not self._db_available:
            if not settings.persistence_fallback_allowed:
                raise PersistenceException("Action item database is unavailable")
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
            logger.warning(f"ActionItem database unavailable; using memory fallback ({exc}).")
        self._db_available = False
        if not settings.persistence_fallback_allowed:
            raise PersistenceException(f"Action item database is unavailable: {exc}") from exc
