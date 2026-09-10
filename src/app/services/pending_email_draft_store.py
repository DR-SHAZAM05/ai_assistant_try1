"""Durable, owner-scoped storage for email drafts awaiting approval."""

from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from sqlalchemy import select

from src.app.core.config import settings
from src.app.core.exceptions import PersistenceException
from src.app.core.logging import logger
from src.app.database.models.models import PendingEmailDraft
from src.app.database.session import AsyncSessionLocal
from src.app.schemas.email import EmailDraftReply


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


_memory_drafts: Dict[str, EmailDraftReply] = {}


class PendingEmailDraftStore:
    """Persist approval state in PostgreSQL in production and memory only in development."""

    def __init__(self, session_factory=AsyncSessionLocal):
        self.session_factory = session_factory

    async def save(self, draft: EmailDraftReply, owner_id: Optional[str]) -> EmailDraftReply:
        draft.owner_id = str(owner_id or "local")
        draft.expires_at = _utcnow_naive() + timedelta(seconds=settings.DRAFT_APPROVAL_TTL_SECONDS)
        if settings.mocks_allowed:
            _memory_drafts[draft.draft_id] = draft
            return draft

        try:
            async with self.session_factory() as session:
                session.add(
                    PendingEmailDraft(
                        draft_id=draft.draft_id,
                        owner_id=draft.owner_id,
                        original_message_id=draft.original_message_id,
                        account_type=draft.account_type,
                        recipient=draft.recipient,
                        subject=draft.subject,
                        body=draft.body,
                        draft_metadata=draft.metadata,
                        status=draft.status,
                        created_at=_utcnow_naive(),
                        expires_at=draft.expires_at,
                    )
                )
                await session.commit()
            return draft
        except Exception as exc:
            raise PersistenceException("Unable to persist the pending email draft") from exc

    async def get(self, draft_id: str, owner_id: Optional[str]) -> Optional[EmailDraftReply]:
        expected_owner = str(owner_id or "local")
        if settings.mocks_allowed:
            draft = _memory_drafts.get(draft_id)
            if not draft or draft.owner_id != expected_owner:
                return None
            if draft.status != "pending_approval" or self._is_expired(draft.expires_at):
                draft.status = "expired" if self._is_expired(draft.expires_at) else draft.status
                return None
            return draft

        try:
            async with self.session_factory() as session:
                record = await session.scalar(
                    select(PendingEmailDraft).where(
                        PendingEmailDraft.draft_id == draft_id,
                        PendingEmailDraft.owner_id == expected_owner,
                        PendingEmailDraft.status == "pending_approval",
                    )
                )
                if not record:
                    return None
                if self._is_expired(record.expires_at):
                    record.status = "expired"
                    record.decided_at = _utcnow_naive()
                    await session.commit()
                    return None
                return self._to_schema(record)
        except PersistenceException:
            raise
        except Exception as exc:
            raise PersistenceException("Unable to load the pending email draft") from exc

    async def get_for_owner(self, owner_id: Optional[str]) -> Optional[EmailDraftReply]:
        expected_owner = str(owner_id or "local")
        if settings.mocks_allowed:
            candidates = [
                draft for draft in _memory_drafts.values()
                if draft.owner_id == expected_owner
                and draft.status == "pending_approval"
                and not self._is_expired(draft.expires_at)
            ]
            return max(candidates, key=lambda draft: draft.expires_at) if candidates else None

        try:
            async with self.session_factory() as session:
                record = await session.scalar(
                    select(PendingEmailDraft)
                    .where(
                        PendingEmailDraft.owner_id == expected_owner,
                        PendingEmailDraft.status == "pending_approval",
                        PendingEmailDraft.expires_at > _utcnow_naive(),
                    )
                    .order_by(PendingEmailDraft.created_at.desc())
                    .limit(1)
                )
                return self._to_schema(record) if record else None
        except Exception as exc:
            raise PersistenceException("Unable to find a pending email draft for this user") from exc

    async def decide(
        self,
        draft_id: str,
        owner_id: Optional[str],
        status: str,
        expected_statuses: tuple[str, ...] = ("pending_approval",),
    ) -> Optional[EmailDraftReply]:
        expected_owner = str(owner_id or "local")
        if settings.mocks_allowed:
            draft = _memory_drafts.get(draft_id)
            if (
                not draft
                or draft.owner_id != expected_owner
                or draft.status not in expected_statuses
                or self._is_expired(draft.expires_at)
            ):
                return None
            draft.status = status
            if status in {"rejected", "sent", "failed", "expired"}:
                _memory_drafts.pop(draft_id, None)
            return draft

        try:
            async with self.session_factory() as session:
                record = await session.scalar(
                    select(PendingEmailDraft)
                    .where(
                        PendingEmailDraft.draft_id == draft_id,
                        PendingEmailDraft.owner_id == expected_owner,
                    )
                    .with_for_update()
                )
                if (
                    not record
                    or record.status not in expected_statuses
                    or self._is_expired(record.expires_at)
                ):
                    if record and self._is_expired(record.expires_at):
                        record.status = "expired"
                        record.decided_at = _utcnow_naive()
                        await session.commit()
                    return None
                record.status = status
                record.decided_at = _utcnow_naive()
                await session.commit()
                return self._to_schema(record)
        except Exception as exc:
            raise PersistenceException("Unable to update the pending email draft") from exc

    @staticmethod
    def _is_expired(expires_at: Optional[datetime]) -> bool:
        return expires_at is None or expires_at <= _utcnow_naive()

    @staticmethod
    def _to_schema(record: PendingEmailDraft) -> EmailDraftReply:
        return EmailDraftReply(
            draft_id=record.draft_id,
            original_message_id=record.original_message_id,
            account_type=record.account_type,
            recipient=record.recipient,
            subject=record.subject,
            body=record.body,
            status=record.status,
            metadata=record.draft_metadata or {},
            owner_id=record.owner_id,
            expires_at=record.expires_at,
        )
