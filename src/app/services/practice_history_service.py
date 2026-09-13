import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, text

from src.app.core.logging import logger
from src.app.core.config import settings
from src.app.core.exceptions import PersistenceException
from src.app.core.user_scope import require_user_id
from src.app.database.models.models import PracticeAnswer, PracticeQuestion
from src.app.database.session import AsyncSessionLocal, engine


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class PracticeExchangeRecord:
    user_id: str
    academic_year: str
    topic: str
    question_summary: str
    answer_summary: str
    source_type: str
    source_reference: Optional[str] = None
    student_name: Optional[str] = None
    student_group: Optional[str] = None
    decision: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utcnow_naive)


_memory_exchanges: Dict[str, List[PracticeExchangeRecord]] = {}


class PracticeHistoryService:
    """
    Stores and retrieves historical practice Q/A summaries.
    PostgreSQL is the primary store; a memory fallback keeps tests and local
    development usable when Postgres is not running.
    """

    def __init__(self, session_factory=AsyncSessionLocal, database_engine=engine):
        self.session_factory = session_factory
        self.database_engine = database_engine
        self._schema_ready = False
        self._db_available = True

    async def save_exchange(
        self,
        *,
        academic_year: str,
        topic: str,
        question_summary: str,
        answer_summary: str,
        source_type: str,
        source_reference: Optional[str] = None,
        student_name: Optional[str] = None,
        student_group: Optional[str] = None,
        decision: Optional[str] = None,
        tags: Optional[List[str]] = None,
        user_id: Optional[str] = None,
    ) -> PracticeExchangeRecord:
        owner_id = require_user_id(user_id)
        record = PracticeExchangeRecord(
            user_id=owner_id,
            academic_year=academic_year,
            topic=topic,
            question_summary=question_summary,
            answer_summary=answer_summary,
            source_type=source_type,
            source_reference=source_reference,
            student_name=student_name,
            student_group=student_group,
            decision=decision,
            tags=tags or [],
        )

        if not await self._can_use_database():
            _memory_exchanges.setdefault(owner_id, []).append(record)
            return record

        try:
            async with self.session_factory() as session:
                question = PracticeQuestion(
                    user_id=owner_id,
                    academic_year=academic_year,
                    student_name=student_name,
                    student_group=student_group,
                    topic=topic,
                    question_summary=question_summary,
                    source_type=source_type,
                    source_reference=source_reference,
                    tags=tags or [],
                    created_at=record.created_at,
                )
                session.add(question)
                await session.flush()

                answer = PracticeAnswer(
                    user_id=owner_id,
                    question_id=question.id,
                    answer_summary=answer_summary,
                    decision=decision,
                    academic_year=academic_year,
                    created_at=record.created_at,
                )
                session.add(answer)
                await session.commit()
                _memory_exchanges.setdefault(owner_id, []).append(record)
                return record
        except Exception as exc:
            self._disable_database(exc)
            _memory_exchanges.setdefault(owner_id, []).append(record)
            return record

    async def find_similar(
        self,
        *,
        query: str,
        academic_year: Optional[str] = None,
        limit: int = 3,
        user_id: Optional[str] = None,
    ) -> List[PracticeExchangeRecord]:
        owner_id = require_user_id(user_id)
        tokens = self._tokens(query)
        if not tokens:
            return []

        if await self._can_use_database():
            try:
                async with self.session_factory() as session:
                    stmt = select(PracticeQuestion, PracticeAnswer).join(
                        PracticeAnswer,
                        PracticeAnswer.question_id == PracticeQuestion.id,
                    )
                    stmt = stmt.where(
                        PracticeQuestion.user_id == owner_id,
                        PracticeAnswer.user_id == owner_id,
                    )
                    if academic_year:
                        stmt = stmt.where(PracticeQuestion.academic_year == academic_year)
                    result = await session.execute(stmt)
                    rows = result.all()
                    records = [
                        PracticeExchangeRecord(
                            user_id=question.user_id,
                            academic_year=question.academic_year,
                            topic=question.topic,
                            question_summary=question.question_summary,
                            answer_summary=answer.answer_summary,
                            source_type=question.source_type,
                            source_reference=question.source_reference,
                            student_name=question.student_name,
                            student_group=question.student_group,
                            decision=answer.decision,
                            tags=question.tags or [],
                            created_at=question.created_at or _utcnow_naive(),
                        )
                        for question, answer in rows
                    ]
                    return self._rank(records, tokens, limit)
            except Exception as exc:
                self._disable_database(exc)

        candidates = [
            record for record in _memory_exchanges.get(owner_id, [])
            if not academic_year or record.academic_year == academic_year
        ]
        return self._rank(candidates, tokens, limit)

    async def _can_use_database(self) -> bool:
        if not self._db_available:
            if not settings.persistence_fallback_allowed:
                raise PersistenceException("Practice history database is unavailable")
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
            logger.warning(f"Practice history database unavailable; using memory fallback ({exc}).")
        self._db_available = False
        if not settings.persistence_fallback_allowed:
            raise PersistenceException(f"Practice history database is unavailable: {exc}") from exc

    @staticmethod
    def _tokens(text: str) -> set:
        return {
            token
            for token in re.findall(r"[a-z0-9ăâîșț]+", text.lower())
            if len(token) >= 4
        }

    @classmethod
    def _rank(cls, records: List[PracticeExchangeRecord], query_tokens: set, limit: int) -> List[PracticeExchangeRecord]:
        scored = []
        for record in records:
            haystack = " ".join([record.topic, record.question_summary, record.answer_summary, " ".join(record.tags)])
            score = len(query_tokens.intersection(cls._tokens(haystack)))
            if score:
                scored.append((score, record))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [record for _, record in scored[:limit]]
