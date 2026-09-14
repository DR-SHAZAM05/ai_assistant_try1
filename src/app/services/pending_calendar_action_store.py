"""PendingCalendarActionStore - Manages pending calendar actions with user isolation and TTL."""

from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from sqlalchemy import select, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.app.core.config import settings
from src.app.database.models.models import PendingCalendarAction


class PendingCalendarActionStore:
    """Thread-safe store for pending calendar actions with expiration."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(
        self,
        owner_id: str,
        action_type: str,
        payload: dict,
        preview_text: str,
    ) -> str:
        """
        Create and save a pending calendar action.

        Args:
            owner_id: User ID who initiated the action
            action_type: "create", "update", "delete"
            payload: Raw action data (event details)
            preview_text: Human-readable preview

        Returns:
            action_id: Unique identifier for this pending action
        """
        from datetime import datetime as dt_cls, timezone
        action_id = str(uuid4())
        now = dt_cls.now(timezone.utc).replace(tzinfo=None)
        expires_at = now + timedelta(seconds=settings.CALENDAR_ACTION_TTL_SECONDS)

        action = PendingCalendarAction(
            action_id=action_id,
            owner_id=owner_id,
            action_type=action_type,
            payload=payload,
            preview_text=preview_text,
            status="pending_approval",
            created_at=now,
            expires_at=expires_at,
            decided_at=None,
        )
        self.session.add(action)
        await self.session.flush()
        return action_id

    async def get(self, action_id: str) -> Optional[PendingCalendarAction]:
        """Retrieve a pending action by ID."""
        stmt = select(PendingCalendarAction).where(
            PendingCalendarAction.action_id == action_id
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_for_user(
        self, action_id: str, owner_id: str
    ) -> Optional[PendingCalendarAction]:
        """
        Retrieve action only if it belongs to the specified user.
        Cross-user security check.
        """
        stmt = select(PendingCalendarAction).where(
            and_(
                PendingCalendarAction.action_id == action_id,
                PendingCalendarAction.owner_id == owner_id,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def decide(
        self,
        action_id: str,
        status: str,
        decided_at: Optional[datetime] = None,
    ) -> bool:
        """
        Mark an action as approved/rejected/expired.

        Args:
            action_id: Action identifier
            status: "approved", "rejected", "expired"
            decided_at: When the decision was made

        Returns:
            True if update succeeded, False if action not found
        """
        from datetime import datetime as dt_cls, timezone
        action = await self.get(action_id)
        if not action:
            return False

        action.status = status
        action.decided_at = decided_at or dt_cls.now(timezone.utc).replace(tzinfo=None)
        await self.session.flush()
        return True

    async def is_expired(self, action_id: str) -> bool:
        """Check if action TTL has elapsed."""
        from datetime import datetime as dt_cls, timezone
        action = await self.get(action_id)
        if not action:
            return True
        return dt_cls.now(timezone.utc).replace(tzinfo=None) > action.expires_at

    async def cleanup_expired(self) -> int:
        """
        Delete expired pending actions (soft delete by marking as expired).
        For audit trail, we mark as 'expired' rather than delete.

        Returns:
            Number of actions marked expired
        """
        from datetime import datetime as dt_cls, timezone
        now = dt_cls.now(timezone.utc).replace(tzinfo=None)
        stmt = (
            select(PendingCalendarAction)
            .where(
                and_(
                    PendingCalendarAction.expires_at <= now,
                    PendingCalendarAction.status == "pending_approval",
                )
            )
        )
        result = await self.session.execute(stmt)
        actions = result.scalars().all()

        for action in actions:
            action.status = "expired"
            action.decided_at = now

        await self.session.flush()
        return len(actions)
