from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import select, text

from src.app.core.config import settings
from src.app.core.exceptions import PersistenceException
from src.app.core.logging import logger
from src.app.database.models.models import PracticeDocument
from src.app.database.session import AsyncSessionLocal, engine


@dataclass
class PracticeDocumentRecord:
    document_id: str
    academic_year: str
    file_name: str
    file_path: str
    document_type: str
    qdrant_collection: str
    checksum: str
    status: str = "processed"
    chunks_count: int = 0
    vectors_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    updated_at: Optional[datetime] = None


_memory_records: Dict[Tuple[str, str, str], PracticeDocumentRecord] = {}


def _utcnow_naive() -> datetime:
    """Return UTC in the format used by the project's TIMESTAMP columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PracticeDocumentRegistry:
    """
    Tracks ingested practice documents in PostgreSQL through PracticeDocument.
    If the database is unavailable, it degrades to process-local memory so local
    tests and development still work, while production keeps persistent checksums.
    """

    def __init__(self, session_factory=AsyncSessionLocal, collection_name: Optional[str] = None):
        self.session_factory = session_factory
        self.collection_name = collection_name or settings.QDRANT_COLLECTION
        self._schema_ready = False
        self._db_available = True

    async def get_document(self, file_path: Path, academic_year: str) -> Optional[PracticeDocumentRecord]:
        key = self._memory_key(file_path, academic_year)
        if not await self._can_use_database():
            return _memory_records.get(key)

        try:
            async with self.session_factory() as session:
                result = await session.execute(
                    select(PracticeDocument).where(
                        PracticeDocument.academic_year == academic_year,
                        PracticeDocument.file_path == self._normalize_path(file_path),
                        PracticeDocument.qdrant_collection == self.collection_name,
                    )
                )
                document = result.scalar_one_or_none()
                return self._to_record(document) if document else None
        except Exception as exc:
            self._disable_database(exc)
            return _memory_records.get(key)

    async def mark_processed(
        self,
        *,
        document_id: str,
        file_path: Path,
        academic_year: str,
        checksum: str,
        document_type: str,
        chunks_count: int,
        vectors_count: int,
        metadata: Optional[Dict[str, Any]] = None,
        status: str = "processed",
    ) -> PracticeDocumentRecord:
        record = PracticeDocumentRecord(
            document_id=document_id,
            academic_year=academic_year,
            file_name=file_path.name,
            file_path=self._normalize_path(file_path),
            document_type=document_type,
            qdrant_collection=self.collection_name,
            checksum=checksum,
            status=status,
            chunks_count=chunks_count,
            vectors_count=vectors_count,
            metadata=metadata or {},
            updated_at=_utcnow_naive(),
        )

        key = self._memory_key(file_path, academic_year)
        if not await self._can_use_database():
            _memory_records[key] = record
            return record

        try:
            async with self.session_factory() as session:
                result = await session.execute(
                    select(PracticeDocument).where(
                        PracticeDocument.academic_year == academic_year,
                        PracticeDocument.file_path == record.file_path,
                        PracticeDocument.qdrant_collection == self.collection_name,
                    )
                )
                document = result.scalar_one_or_none()
                if document is None:
                    document = PracticeDocument(
                        document_id=document_id,
                        academic_year=academic_year,
                        file_name=file_path.name,
                        file_path=record.file_path,
                        document_type=document_type,
                        qdrant_collection=self.collection_name,
                        checksum=checksum,
                    )
                    session.add(document)

                document.document_id = document_id
                document.file_name = file_path.name
                document.document_type = document_type
                document.checksum = checksum
                document.status = status
                document.chunks_count = chunks_count
                document.vectors_count = vectors_count
                document.document_metadata = metadata or {}
                document.updated_at = record.updated_at

                await session.commit()
                _memory_records[key] = record
                return record
        except Exception as exc:
            self._disable_database(exc)
            _memory_records[key] = record
            return record

    async def mark_failed(
        self,
        *,
        document_id: str,
        file_path: Path,
        academic_year: str,
        checksum: str,
        document_type: str,
        error: str,
    ) -> PracticeDocumentRecord:
        return await self.mark_processed(
            document_id=document_id,
            file_path=file_path,
            academic_year=academic_year,
            checksum=checksum,
            document_type=document_type,
            chunks_count=0,
            vectors_count=0,
            metadata={"error": error},
            status="failed",
        )

    async def _can_use_database(self) -> bool:
        if not self._db_available:
            if not settings.mocks_allowed:
                raise PersistenceException("Practice document registry database is unavailable")
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
            logger.warning(
                "PracticeDocument registry database unavailable; using memory fallback (%s).",
                type(exc).__name__,
            )
        self._db_available = False
        if not settings.mocks_allowed:
            raise PersistenceException("Practice document registry database is unavailable") from exc

    def _memory_key(self, file_path: Path, academic_year: str) -> Tuple[str, str, str]:
        return (academic_year, self._normalize_path(file_path), self.collection_name)

    @staticmethod
    def _normalize_path(file_path: Path) -> str:
        return str(file_path.resolve())

    @staticmethod
    def _to_record(document: PracticeDocument) -> PracticeDocumentRecord:
        return PracticeDocumentRecord(
            document_id=document.document_id,
            academic_year=document.academic_year,
            file_name=document.file_name,
            file_path=document.file_path,
            document_type=document.document_type,
            qdrant_collection=document.qdrant_collection,
            checksum=document.checksum,
            status=document.status,
            chunks_count=document.chunks_count,
            vectors_count=document.vectors_count,
            metadata=document.document_metadata or {},
            updated_at=document.updated_at,
        )
