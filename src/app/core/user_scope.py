"""Utilities for preventing accidental cross-user persistence."""

from typing import Optional

from src.app.core.config import settings
from src.app.core.exceptions import PersistenceException


LEGACY_UNASSIGNED_USER_ID = "__legacy_unassigned__"
TEST_USER_ID = "__test_user__"
_RESERVED_USER_IDS = {"default", LEGACY_UNASSIGNED_USER_ID}


def require_user_id(user_id: Optional[str]) -> str:
    """Return a validated Telegram owner id for any user-scoped operation.

    Production and development paths must always pass an explicit Telegram user
    id.  Tests may omit it to keep isolated fixture calls concise; that value is
    never available from a live Telegram request.
    """

    normalized = str(user_id or "").strip()
    if not normalized:
        if settings.APP_ENV.lower() in {"test", "testing"}:
            return TEST_USER_ID
        raise PersistenceException("A Telegram user id is required for user-scoped persistence")
    if normalized in _RESERVED_USER_IDS:
        raise PersistenceException("The supplied user id is reserved and cannot access user data")
    if len(normalized) > 64:
        raise PersistenceException("Telegram user id exceeds the supported length")
    return normalized
