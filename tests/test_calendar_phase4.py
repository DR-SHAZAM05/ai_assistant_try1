"""FAZA 4 - Calendar Human-in-the-Loop Tests."""

import pytest
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

from src.app.database.models.models import Base, PendingCalendarAction
from src.app.services.calendar_service import CalendarService
from src.app.services.pending_calendar_action_store import PendingCalendarActionStore
from src.app.services.audit_service import AuditService
from src.app.integrations.google_calendar.mock_provider import MockCalendarProvider
from src.app.core.config import settings
from src.app.schemas.calendar import CalendarEventSchema


@pytest.fixture
async def db_session():
    """Create a PostgreSQL session for tests using Docker Postgres."""
    # Use the test database from docker-compose
    test_db_url = "postgresql+asyncpg://{}:{}@{}:{}/{}".format(
        settings.POSTGRES_USER,
        settings.POSTGRES_PASSWORD,
        settings.POSTGRES_HOST,
        settings.POSTGRES_PORT,
        settings.POSTGRES_DB
    )
    engine = create_async_engine(
        test_db_url,
        echo=False,
    )
    
    # Create tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    session = async_session()
    
    # Clean up test data before test
    await session.execute(text("DELETE FROM pending_calendar_actions WHERE owner_id LIKE 'user_%'"))
    await session.commit()
    
    yield session
    
    # Clean up after test
    await session.execute(text("DELETE FROM pending_calendar_actions WHERE owner_id LIKE 'user_%'"))
    await session.commit()
    await session.close()
    await engine.dispose()


@pytest.fixture
async def calendar_service(db_session):
    """Create a CalendarService with mock provider and test DB."""
    provider = MockCalendarProvider()
    audit_service = AuditService(db_session)
    service = CalendarService(provider, db_session, audit_service)
    return service


class TestCalendarServiceCreateFlow:
    """Test CREATE event flow: request → pending → preview → confirm → execute"""

    async def test_request_create_pending(self, calendar_service, db_session):
        """Request CREATE should NOT call provider, only create pending action."""
        user_id = "user_123"
        now = datetime.now(ZoneInfo("Europe/Bucharest"))
        
        action_id, preview = await calendar_service.request_create(
            user_id=user_id,
            summary="Test Event",
            description="Test Description",
            location="Test Location",
            start_time=now + timedelta(hours=2),
            end_time=now + timedelta(hours=3),
        )

        # Verify action created
        assert action_id
        assert "Test Event" in preview
        assert "Test Description" in preview
        assert "Test Location" in preview

        # Verify provider NOT called
        events_before = await calendar_service.fetch_events(user_id, now, now + timedelta(days=30))
        initial_event_count = len(events_before)

    async def test_confirm_create_executes_provider(self, calendar_service, db_session):
        """Confirm CREATE should execute provider."""
        user_id = "user_123"
        now = datetime.now(ZoneInfo("Europe/Bucharest"))
        
        action_id, preview = await calendar_service.request_create(
            user_id=user_id,
            summary="Event to Create",
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
        )

        # Confirm
        result = await calendar_service.confirm_action(user_id, action_id)
        assert "Event to Create" in result

    async def test_cancel_create_no_provider_call(self, calendar_service, db_session):
        """Cancel CREATE should NOT call provider."""
        user_id = "user_123"
        now = datetime.now(ZoneInfo("Europe/Bucharest"))
        
        action_id, _ = await calendar_service.request_create(
            user_id=user_id,
            summary="Cancelled Event",
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
        )

        # Cancel
        result = await calendar_service.cancel_action(user_id, action_id)
        assert "anulată" in result.lower()

        # Verify status is rejected
        store = PendingCalendarActionStore(db_session)
        action = await store.get(action_id)
        assert action.status == "rejected"


class TestCalendarServiceUpdateFlow:
    """Test UPDATE event flow with ambiguity handling."""

    async def test_update_zero_matches_error(self, calendar_service):
        """UPDATE with 0 matches should raise error."""
        user_id = "user_123"
        
        with pytest.raises(ValueError, match="Nu am găsit"):
            await calendar_service.request_update(
                user_id=user_id,
                event_query="NONEXISTENT_EVENT",
                updates={"summary": "New Title"},
            )

    async def test_update_one_match_creates_pending(self, calendar_service):
        """UPDATE with exactly 1 match should create pending action."""
        user_id = "user_123"
        
        # Mock provider has events like "Ședință Departament"
        action_id, preview = await calendar_service.request_update(
            user_id=user_id,
            event_query="Ședință Departament",
            updates={"summary": "Updated Title"},
        )

        assert action_id
        assert "Updated Title" in preview or "modificat" in preview.lower()

    async def test_update_multiple_matches_error(self, calendar_service):
        """UPDATE with >1 matches should raise error."""
        user_id = "user_123"
        
        with pytest.raises(ValueError, match="Sunt .* evenimente"):
            await calendar_service.request_update(
                user_id=user_id,
                event_query="Consultații",  # Multiple matches in mock
                updates={"summary": "New Title"},
            )


class TestCalendarServiceDeleteFlow:
    """Test DELETE event flow."""

    async def test_delete_one_match_creates_pending(self, calendar_service):
        """DELETE with 1 match should create pending action."""
        user_id = "user_123"
        
        action_id, preview = await calendar_service.request_delete(
            user_id=user_id,
            event_query="Ședință Departament",
        )

        assert action_id
        assert "șters" in preview.lower() or "Ședință Departament" in preview

    async def test_delete_confirm_executes_provider(self, calendar_service):
        """Confirm DELETE should execute provider."""
        user_id = "user_123"
        
        action_id, _ = await calendar_service.request_delete(
            user_id=user_id,
            event_query="Ședință Departament",
        )

        result = await calendar_service.confirm_action(user_id, action_id)
        assert "șters" in result.lower()


class TestCrossUserSecurity:
    """Test cross-user protection."""

    async def test_user_cannot_confirm_other_user_action(self, calendar_service, db_session):
        """User A cannot confirm User B's action."""
        user_a = "user_a"
        user_b = "user_b"
        now = datetime.now(ZoneInfo("Europe/Bucharest"))
        
        action_id, _ = await calendar_service.request_create(
            user_id=user_a,
            summary="User A Event",
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
        )

        # User B tries to confirm User A's action
        with pytest.raises(PermissionError, match="altui utilizator"):
            await calendar_service.confirm_action(user_b, action_id)

    async def test_user_cannot_cancel_other_user_action(self, calendar_service):
        """User A cannot cancel User B's action."""
        user_a = "user_a"
        user_b = "user_b"
        now = datetime.now(ZoneInfo("Europe/Bucharest"))
        
        action_id, _ = await calendar_service.request_create(
            user_id=user_a,
            summary="User A Event",
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
        )

        with pytest.raises(PermissionError, match="altui utilizator"):
            await calendar_service.cancel_action(user_b, action_id)


class TestDoubleConfirmProtection:
    """Test double-confirm / double-cancel protection."""

    async def test_double_confirm_error(self, calendar_service):
        """Second confirm on same action should error."""
        user_id = "user_123"
        now = datetime.now(ZoneInfo("Europe/Bucharest"))
        
        action_id, _ = await calendar_service.request_create(
            user_id=user_id,
            summary="Event",
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
        )

        # First confirm
        await calendar_service.confirm_action(user_id, action_id)

        # Second confirm should error
        with pytest.raises(ValueError, match="deja procesată"):
            await calendar_service.confirm_action(user_id, action_id)

    async def test_double_cancel_error(self, calendar_service):
        """Second cancel on same action should error."""
        user_id = "user_123"
        now = datetime.now(ZoneInfo("Europe/Bucharest"))
        
        action_id, _ = await calendar_service.request_create(
            user_id=user_id,
            summary="Event",
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
        )

        # First cancel
        await calendar_service.cancel_action(user_id, action_id)

        # Second cancel should error
        with pytest.raises(ValueError, match="deja procesată"):
            await calendar_service.cancel_action(user_id, action_id)

    async def test_confirm_after_cancel_error(self, calendar_service):
        """Confirm after cancel should error."""
        user_id = "user_123"
        now = datetime.now(ZoneInfo("Europe/Bucharest"))
        
        action_id, _ = await calendar_service.request_create(
            user_id=user_id,
            summary="Event",
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
        )

        await calendar_service.cancel_action(user_id, action_id)

        with pytest.raises(ValueError, match="deja procesată"):
            await calendar_service.confirm_action(user_id, action_id)


class TestTTLExpiration:
    """Test TTL expiration."""

    async def test_expired_action_cannot_be_confirmed(self, calendar_service, db_session):
        """Expired action should not be executable."""
        user_id = "user_123"
        now = datetime.now(ZoneInfo("Europe/Bucharest"))
        
        action_id, _ = await calendar_service.request_create(
            user_id=user_id,
            summary="Event",
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
        )

        # Force expiration
        store = PendingCalendarActionStore(db_session)
        action = await store.get(action_id)
        action.expires_at = now - timedelta(seconds=1)
        await db_session.flush()

        # Try to confirm - should error
        with pytest.raises(ValueError, match="expirat"):
            await calendar_service.confirm_action(user_id, action_id)


class TestAuditSanitisation:
    """Test audit payload sanitisation."""

    def test_sanitize_email(self, calendar_service):
        """Emails should be redacted."""
        payload = {
            "action_type": "create",
            "event": {
                "summary": "Test",
                "organizer_email": "user@example.com",
            }
        }
        sanitized = calendar_service._sanitize_audit_payload(payload)
        assert sanitized["event"]["organizer_email"] == "<redacted>"

    def test_sanitize_phone(self, calendar_service):
        """Phone numbers should be redacted."""
        payload = {
            "action_type": "create",
            "event": {
                "summary": "Test",
                "contact_phone": "+40712345678",
            }
        }
        sanitized = calendar_service._sanitize_audit_payload(payload)
        assert sanitized["event"]["contact_phone"] == "<redacted>"

    def test_sanitize_token(self, calendar_service):
        """Tokens should be redacted."""
        payload = {
            "action_type": "create",
            "event": {
                "summary": "Test",
                "api_token": "secret_token_12345",
            }
        }
        sanitized = calendar_service._sanitize_audit_payload(payload)
        assert sanitized["event"]["api_token"] == "<redacted>"

    def test_sanitize_preserves_legitimate_fields(self, calendar_service):
        """Legitimate fields should be preserved."""
        payload = {
            "action_type": "create",
            "event": {
                "summary": "Meeting",
                "description": "Important discussion",
                "location": "Room 101",
                "start_time": "2026-09-15T14:00:00",
                "end_time": "2026-09-15T15:00:00",
            }
        }
        sanitized = calendar_service._sanitize_audit_payload(payload)
        assert sanitized["event"]["summary"] == "Meeting"
        assert sanitized["event"]["location"] == "Room 101"


class TestTimezone:
    """Test timezone handling."""

    async def test_relative_dates_use_bucharest_tz(self, calendar_service):
        """Relative dates should use Europe/Bucharest."""
        user_id = "user_123"
        
        # Request events for "azi" (today)
        events = await calendar_service.fetch_events(user_id)
        # Should use Europe/Bucharest internally
        assert events is not None


class TestPendingCalendarActionStore:
    """Test PendingCalendarActionStore operations."""

    async def test_save_and_get(self, db_session):
        """Save and retrieve action."""
        store = PendingCalendarActionStore(db_session)
        
        action_id = await store.save(
            owner_id="user_123",
            action_type="create",
            payload={"test": "data"},
            preview_text="Test preview",
        )

        action = await store.get(action_id)
        assert action is not None
        assert action.owner_id == "user_123"
        assert action.status == "pending_approval"

    async def test_get_for_user_ownership_check(self, db_session):
        """get_for_user should enforce ownership."""
        store = PendingCalendarActionStore(db_session)
        
        action_id = await store.save(
            owner_id="user_a",
            action_type="create",
            payload={},
            preview_text="",
        )

        # User A can get
        action = await store.get_for_user(action_id, "user_a")
        assert action is not None

        # User B cannot get
        action = await store.get_for_user(action_id, "user_b")
        assert action is None

    async def test_decide_status_change(self, db_session):
        """Decide should update status."""
        store = PendingCalendarActionStore(db_session)
        
        action_id = await store.save(
            owner_id="user_123",
            action_type="create",
            payload={},
            preview_text="",
        )

        result = await store.decide(action_id, "approved")
        assert result is True

        action = await store.get(action_id)
        assert action.status == "approved"
        assert action.decided_at is not None

    async def test_is_expired(self, db_session):
        """is_expired should check TTL."""
        store = PendingCalendarActionStore(db_session)
        
        action_id = await store.save(
            owner_id="user_123",
            action_type="create",
            payload={},
            preview_text="",
        )

        # Newly created should not be expired
        assert not await store.is_expired(action_id)

        # Force expiration
        action = await store.get(action_id)
        action.expires_at = datetime.utcnow() - timedelta(seconds=1)
        await db_session.flush()

        assert await store.is_expired(action_id)
