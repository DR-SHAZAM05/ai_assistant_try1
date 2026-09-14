"""
Q/A Semantic Indexing Service.

Indexes practice question/answer summaries into the Qdrant vector store so they can be
retrieved semantically, not just via lexical matching.

Design:
  - PostgreSQL is the source of truth for full Q/A data.
  - Qdrant stores: embedding + lightweight metadata + reference to PostgreSQL row.
  - user_id is always set (Q/A records are user-private, never global).
  - academic_year filter applies normally.
  - Collection: same as documents (practice_knowledge*) but document_type="qa_summary".
"""

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.app.core.config import settings
from src.app.core.logging import logger
from src.app.core.exceptions import RAGRetrievalException
from src.app.rag.embeddings import EmbeddingProvider, get_embedding_provider
from src.app.rag.vector_store import QdrantVectorStore
from src.app.schemas.rag import RAGChunkSchema


def _qa_document_id(user_id: str, academic_year: str, question_summary: str) -> str:
    """Stable document_id for a Q/A pair derived from content hash."""
    content = f"{user_id}::{academic_year}::{question_summary}"
    sha = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    return f"qa-{sha}"


def _qa_chunk_id(document_id: str, qa_type: str) -> str:
    """chunk_id for question or answer part of a Q/A pair."""
    return f"{document_id}-{qa_type}"


def _qa_text(question_summary: str, answer_summary: str) -> str:
    """
    Combined text for embedding: question + answer together for semantic richness.
    Qdrant stores the full combined text; retrieval returns this as the chunk payload.
    """
    return f"Întrebare: {question_summary}\nRăspuns: {answer_summary}"


class QAIndexingService:
    """
    Indexes practice Q/A summaries from PracticeHistoryService into Qdrant for
    semantic retrieval in addition to the existing lexical find_similar().

    Usage:
        service = QAIndexingService()
        await service.index_exchange(
            user_id="123456",
            academic_year="2026-2027",
            topic="erasmus",
            question_summary="...",
            answer_summary="...",
            source_type="telegram",
            source_reference="Ghid_Practica_2026_2027.md",
        )
    """

    DOCUMENT_TYPE = "qa_summary"

    def __init__(
        self,
        vector_store: Optional[QdrantVectorStore] = None,
        embedding_provider: Optional[EmbeddingProvider] = None,
    ):
        self.vector_store = vector_store or QdrantVectorStore()
        self.embedding_provider = embedding_provider or get_embedding_provider()

    async def index_exchange(
        self,
        *,
        user_id: str,
        academic_year: str,
        topic: str,
        question_summary: str,
        answer_summary: str,
        source_type: str,
        source_reference: Optional[str] = None,
        tags: Optional[List[str]] = None,
        created_at: Optional[datetime] = None,
    ) -> bool:
        """
        Embed a Q/A exchange and upsert it into Qdrant.

        Returns True on success, False on failure (non-fatal — PostgreSQL remains source of truth).
        """
        if not question_summary or not answer_summary:
            logger.warning("QAIndexingService: skipping empty Q/A pair for user %s.", user_id)
            return False

        combined_text = _qa_text(question_summary, answer_summary)
        document_id = _qa_document_id(user_id, academic_year, question_summary)
        chunk_id = _qa_chunk_id(document_id, "qa")
        checksum = hashlib.sha256(combined_text.encode("utf-8")).hexdigest()
        indexed_at = (created_at or datetime.now(timezone.utc)).isoformat()

        chunk = RAGChunkSchema(
            chunk_id=chunk_id,
            document_id=document_id,
            filename=f"qa_{topic}_{academic_year}.summary",
            academic_year=academic_year,
            page=1,
            chunk_index=0,
            source_path=source_reference or f"qa://{user_id}/{academic_year}/{document_id}",
            text=combined_text,
            checksum=checksum,
            document_type=self.DOCUMENT_TYPE,
            category=f"qa/{topic}",
            user_id=user_id,  # Q/A records are ALWAYS user-private
            metadata={
                "topic": topic,
                "source_type": source_type,
                "source_reference": source_reference,
                "tags": tags or [],
                "indexed_at": indexed_at,
            },
        )

        try:
            await self.vector_store.init_collection(vector_size=settings.EMBEDDING_VECTOR_SIZE)

            # Remove any previous version of this Q/A (same document_id + user_id)
            await self.vector_store.delete_document_vectors(
                document_id=document_id,
                user_id=user_id,
            )

            vector = await self.embedding_provider.embed_text(combined_text)
            if len(vector) != settings.EMBEDDING_VECTOR_SIZE:
                raise RAGRetrievalException(
                    f"QA embedding size mismatch: expected {settings.EMBEDDING_VECTOR_SIZE}, got {len(vector)}"
                )

            await self.vector_store.upsert_chunks([chunk], [vector])
            logger.info(
                "QAIndexingService: indexed Q/A for user=%s year=%s topic=%s.",
                user_id,
                academic_year,
                topic,
            )
            return True
        except Exception as exc:
            logger.warning(
                "QAIndexingService: failed to index Q/A for user=%s (%s). PostgreSQL data is safe.",
                user_id,
                type(exc).__name__,
            )
            return False

    async def search_qa(
        self,
        *,
        query: str,
        user_id: str,
        academic_year: Optional[str] = None,
        top_k: int = 3,
        score_threshold: float = 0.30,
    ) -> List[Dict[str, Any]]:
        """
        Semantic search over indexed Q/A summaries for a specific user.
        Always applies user_id filter — Q/A records are user-private.
        """
        target_year = academic_year or settings.CURRENT_ACADEMIC_YEAR
        try:
            query_vector = await self.embedding_provider.embed_text(query)
            hits = await self.vector_store.search_similarity(
                query_vector=query_vector,
                academic_year=target_year,
                user_id=user_id,
                top_k=top_k,
                score_threshold=score_threshold,
                query_text=query,
            )
            # Filter to only Q/A type results
            qa_hits = [h for h in hits if h.get("payload", {}).get("document_type") == self.DOCUMENT_TYPE]
            logger.info(
                "QAIndexingService: semantic search found %d Q/A hits for user=%s.",
                len(qa_hits),
                user_id,
            )
            return qa_hits
        except Exception as exc:
            logger.warning(
                "QAIndexingService: semantic Q/A search failed for user=%s (%s).",
                user_id,
                type(exc).__name__,
            )
            return []
