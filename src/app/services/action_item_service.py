from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import select, text

from src.app.core.logging import logger
from src.app.core.config import settings
from src.app.core.exceptions import PersistenceException
from src.app.database.models.models import ActionItem, ActionStatusEnum, PriorityEnum
from src.app.database.session import AsyncSessionLocal, engine


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


_memory_action_items: List[Dict[str, Any]] = []


class ActionItemService:
    """
    Manages Action Items and Tasks extracted from emails, calendar, and practice questions.
    Backed by PostgreSQL (action_items table), with in-memory fallback.
    """

    def __init__(self, session_factory=AsyncSessionLocal):
        self.session_factory = session_factory
        self._schema_ready = False
        self._db_available = True

    async def create_action_item(
        self,
        title: str,
        source: str,
        deadline: Optional[datetime] = None,
        priority: str = "medium",
        source_reference: Optional[str] = None,
    ) -> Dict[str, Any]:
        if deadline and getattr(deadline, "tzinfo", None) is not None:
            deadline = deadline.astimezone(timezone.utc).replace(tzinfo=None)

        item_dict = {
            "id": len(_memory_action_items) + 1,
            "title": title,
            "source": source,
            "deadline": deadline,
            "priority": priority,
            "status": "open",
            "source_reference": source_reference,
            "created_at": _utcnow_naive(),
        }

        if not await self._can_use_database():
            for m in _memory_action_items:
                if source_reference and m.get("source_reference") == source_reference:
                    m["title"] = title
                    if deadline:
                        m["deadline"] = deadline
                    return m
            _memory_action_items.append(item_dict)
            return item_dict

        try:
            async with self.session_factory() as session:
                if source_reference:
                    stmt = select(ActionItem).where(ActionItem.source_reference == source_reference)
                    res = await session.execute(stmt)
                    existing = res.scalar_one_or_none()
                    if existing:
                        existing.title = title
                        if deadline:
                            existing.deadline = deadline
                        await session.commit()
                        return {
                            "id": existing.id,
                            "title": existing.title,
                            "source": existing.source,
                            "deadline": existing.deadline,
                            "priority": existing.priority.value if hasattr(existing.priority, "value") else str(existing.priority),
                            "status": existing.status.value if hasattr(existing.status, "value") else str(existing.status),
                            "source_reference": existing.source_reference,
                            "created_at": existing.created_at,
                        }

                p_enum = PriorityEnum.MEDIUM
                if priority.lower() == "high":
                    p_enum = PriorityEnum.HIGH
                elif priority.lower() == "low":
                    p_enum = PriorityEnum.LOW

                ai = ActionItem(
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
                _memory_action_items.append(item_dict)
                return item_dict
        except Exception as exc:
            self._disable_database(exc)
            _memory_action_items.append(item_dict)
            return item_dict

    async def list_action_items(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        if await self._can_use_database():
            try:
                async with self.session_factory() as session:
                    stmt = select(ActionItem)
                    if status:
                        try:
                            s_enum = ActionStatusEnum(status.lower())
                            stmt = stmt.where(ActionItem.status == s_enum)
                        except ValueError:
                            stmt = stmt.where(ActionItem.status == status)
                    res = await session.execute(stmt)
                    rows = res.scalars().all()
                    return [
                        {
                            "id": r.id,
                            "title": r.title,
                            "source": r.source,
                            "deadline": r.deadline,
                            "priority": r.priority.value if hasattr(r.priority, "value") else str(r.priority),
                            "status": r.status.value if hasattr(r.status, "value") else str(r.status),
                            "source_reference": r.source_reference,
                        }
                        for r in rows
                    ]
            except Exception as exc:
                self._disable_database(exc)

        items = list(_memory_action_items)
        if status:
            items = [i for i in items if i.get("status") == status]
        return items

    async def update_action_item_status(self, item_id: int, new_status: str) -> bool:
        for item in _memory_action_items:
            if item["id"] == item_id:
                item["status"] = new_status

        if not await self._can_use_database():
            return True

        try:
            async with self.session_factory() as session:
                stmt = select(ActionItem).where(ActionItem.id == item_id)
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
            return True

    async def _can_use_database(self) -> bool:
        if not self._db_available:
            if not settings.mocks_allowed:
                raise PersistenceException("Action item database is unavailable")
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
            logger.warning(f"ActionItem database unavailable; using memory fallback ({exc}).")
        self._db_available = False
        if not settings.mocks_allowed:
            raise PersistenceException(f"Action item database is unavailable: {exc}") from exc
