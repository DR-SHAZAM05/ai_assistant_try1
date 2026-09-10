import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, text

from src.app.core.config import settings
from src.app.core.exceptions import PersistenceException
from src.app.core.logging import logger
from src.app.database.models.models import AuditLog
from src.app.database.session import AsyncSessionLocal, engine


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class AuditLogRecord:
    timestamp: datetime
    user_request: Optional[str]
    selected_tool: Optional[str]
    model_used: Optional[str]
    status: str
    execution_duration_ms: Optional[float]
    external_operation: Optional[str]
    rag_sources: Optional[List[Dict[str, Any]]] = None


_memory_audit_logs: List[AuditLogRecord] = []


class AuditService:
    """
    Security and observability audit log service.
    Persists structured audit events into PostgreSQL audit_logs table,
    with automatic redaction of sensitive credentials and personal data.
    """

    def __init__(self, session_factory=AsyncSessionLocal):
        self.session_factory = session_factory
        self._schema_ready = False
        self._db_available = True

    @staticmethod
    def sanitize_text(text: Optional[str]) -> Optional[str]:
        if not text:
            return text
        # Redact API keys and tokens
        cleaned = re.sub(r"(sk-[a-zA-Z0-9_-]{10,})", "[REDACTED_API_KEY]", text)
        cleaned = re.sub(r"(Bearer\s+[a-zA-Z0-9._-]{10,})", "Bearer [REDACTED_TOKEN]", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(
            r"(password|secret|token|api[_-]?key)\s*=\s*[^\s,;&]+",
            r"\1=[REDACTED]",
            cleaned,
            flags=re.IGNORECASE,
        )
        return cleaned

    async def log_event(
        self,
        *,
        user_request: Optional[str] = None,
        selected_tool: Optional[str] = None,
        model_used: Optional[str] = None,
        status: str = "success",
        execution_duration_ms: Optional[float] = None,
        external_operation: Optional[str] = None,
        rag_sources: Optional[List[Dict[str, Any]]] = None,
    ) -> AuditLogRecord:
        if not settings.AUDIT_LOG_ENABLED:
            return None

        sanitized_request = (
            self.sanitize_text(user_request) if settings.AUDIT_LOG_STORE_REQUEST_CONTENT else None
        )
        record = AuditLogRecord(
            timestamp=_utcnow_naive(),
            user_request=sanitized_request,
            selected_tool=selected_tool,
            model_used=model_used or settings.DEFAULT_MODEL,
            status=status,
            execution_duration_ms=execution_duration_ms,
            external_operation=external_operation,
            rag_sources=rag_sources,
        )

        if not await self._can_use_database():
            _memory_audit_logs.append(record)
            return record

        try:
            async with self.session_factory() as session:
                log_entry = AuditLog(
                    timestamp=record.timestamp,
                    user_request=record.user_request,
                    selected_tool=record.selected_tool,
                    model_used=record.model_used,
                    status=record.status,
                    execution_duration_ms=record.execution_duration_ms,
                    external_operation=record.external_operation,
                    rag_sources=record.rag_sources,
                )
                session.add(log_entry)
                await session.commit()
                _memory_audit_logs.append(record)
                return record
        except Exception as exc:
            self._disable_database(exc)
            _memory_audit_logs.append(record)
            return record

    async def get_recent_logs(self, limit: int = 10) -> List[AuditLogRecord]:
        if await self._can_use_database():
            try:
                async with self.session_factory() as session:
                    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
                    result = await session.execute(stmt)
                    rows = result.scalars().all()
                    return [
                        AuditLogRecord(
                            timestamp=row.timestamp,
                            user_request=row.user_request,
                            selected_tool=row.selected_tool,
                            model_used=row.model_used,
                            status=row.status,
                            execution_duration_ms=row.execution_duration_ms,
                            external_operation=row.external_operation,
                            rag_sources=row.rag_sources,
                        )
                        for row in rows
                    ]
            except Exception as exc:
                self._disable_database(exc)

        return list(reversed(_memory_audit_logs[-limit:]))

    async def _can_use_database(self) -> bool:
        if not self._db_available:
            if not settings.mocks_allowed:
                raise PersistenceException("Audit database is unavailable")
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
            logger.warning("Audit log database unavailable; using memory fallback (%s).", type(exc).__name__)
        self._db_available = False
        if not settings.mocks_allowed:
            raise PersistenceException(f"Audit database is unavailable: {exc}") from exc
