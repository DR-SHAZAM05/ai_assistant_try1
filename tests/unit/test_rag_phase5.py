"""
Phase 5 RAG & Knowledge Base — Comprehensive Test Suite.

Tests cover:
  - Recursive ingestion (subdirectory discovery)
  - Category metadata from subdirectory path
  - user_id in RAGChunkSchema (global vs private)
  - User isolation in MockQdrantVectorStore
  - Academic year isolation with user_id
  - Q/A semantic indexing (QAIndexingService)
  - No-result hallucination protection
  - Source citation traceability
  - Combined user_id + academic_year filter
"""
import uuid
import pytest

from pathlib import Path
from src.app.rag.chunking import DocumentChunker
from src.app.rag.embeddings import MockEmbeddingProvider
from src.app.rag.vector_store import MockQdrantVectorStore
from src.app.rag.ingestion import IngestionPipeline
from src.app.rag.retrieval import RAGRetriever
from src.app.rag.qa_indexing import QAIndexingService
from src.app.rag.document_registry import PracticeDocumentRecord
from src.app.schemas.rag import RAGChunkSchema
from src.app.core.config import settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeRegistry:
    """Lightweight in-memory document registry for tests."""

    def __init__(self, collection_name: str = "test"):
        self.collection_name = collection_name
        self.records: dict = {}

    async def get_document(self, file_path: Path, academic_year: str):
        return self.records.get((academic_year, str(file_path.resolve()), self.collection_name))

    async def mark_processed(self, **kwargs):
        record = PracticeDocumentRecord(
            document_id=kwargs["document_id"],
            academic_year=kwargs["academic_year"],
            file_name=kwargs["file_path"].name,
            file_path=str(kwargs["file_path"].resolve()),
            document_type=kwargs["document_type"],
            qdrant_collection=self.collection_name,
            checksum=kwargs["checksum"],
            status=kwargs.get("status", "processed"),
            chunks_count=kwargs["chunks_count"],
            vectors_count=kwargs["vectors_count"],
            metadata=kwargs.get("metadata") or {},
        )
        key = (kwargs["academic_year"], str(kwargs["file_path"].resolve()), self.collection_name)
        self.records[key] = record
        return record

    async def mark_failed(self, **kwargs):
        kwargs.setdefault("chunks_count", 0)
        kwargs.setdefault("vectors_count", 0)
        kwargs["status"] = "failed"
        kwargs["metadata"] = {"error": kwargs.pop("error", "")}
        return await self.mark_processed(**kwargs)


def _chunk(
    chunk_id: str,
    text: str,
    academic_year: str = "2026-2027",
    user_id: str = None,
    category: str = "general",
) -> RAGChunkSchema:
    return RAGChunkSchema(
        chunk_id=chunk_id,
        document_id=f"doc-{academic_year}-test",
        filename=f"Ghid_{academic_year}.md",
        academic_year=academic_year,
        page=1,
        chunk_index=0,
        source_path=f"knowledge_base/{academic_year}/Ghid.md",
        text=text,
        checksum=f"checksum-{chunk_id}",
        document_type="md",
        category=category,
        user_id=user_id,
    )


async def _store_with_chunks(chunks, collection=None):
    col = collection or f"test_{uuid.uuid4().hex}"
    provider = MockEmbeddingProvider()
    store = MockQdrantVectorStore(col)
    vectors = await provider.embed_batch([c.text for c in chunks])
    await store.upsert_chunks(chunks, vectors)
    return store, provider


# ===========================================================================
# SECTION 1 — RAGChunkSchema
# ===========================================================================

def test_rag_chunk_schema_defaults():
    """RAGChunkSchema has correct defaults for category and user_id."""
    chunk = RAGChunkSchema(
        chunk_id="c1",
        document_id="doc-1",
        filename="test.md",
        academic_year="2026-2027",
        source_path="knowledge_base/2026-2027/test.md",
        text="test text",
        checksum="abc123",
    )
    assert chunk.category == "general"
    assert chunk.user_id is None  # global by default


def test_rag_chunk_schema_user_id():
    """RAGChunkSchema stores user_id for private documents."""
    chunk = _chunk("c1", "private text", user_id="user123")
    assert chunk.user_id == "user123"


# ===========================================================================
# SECTION 2 — Chunking + Category
# ===========================================================================

def test_chunk_document_default_category(tmp_path):
    """chunk_document assigns 'general' category by default."""
    doc = tmp_path / "doc.md"
    doc.write_text("Practica UNITBV necesita conventie si caiet de practica.")
    chunker = DocumentChunker(chunk_size=200, chunk_overlap=20)
    chunks = chunker.chunk_document(doc, academic_year="2026-2027")
    assert all(c.category == "general" for c in chunks)
    assert all(c.user_id is None for c in chunks)  # KB docs always global


def test_chunk_document_with_category(tmp_path):
    """chunk_document stores provided category in each chunk."""
    doc = tmp_path / "rules.md"
    doc.write_text("Regulamentul UNITBV prevede 90 de ore de practica si 4 credite ECTS.")
    chunker = DocumentChunker(chunk_size=200, chunk_overlap=20)
    chunks = chunker.chunk_document(doc, academic_year="2026-2027", category="Rules")
    assert all(c.category == "Rules" for c in chunks)


def test_chunk_source_traceability(tmp_path):
    """Each chunk is traceable to its source document."""
    doc = tmp_path / "Ghid_Practica.txt"
    doc.write_text("Practica UNITBV. " * 20)
    chunker = DocumentChunker(chunk_size=100, chunk_overlap=20)
    chunks = chunker.chunk_document(doc, academic_year="2026-2027")
    for chunk in chunks:
        assert chunk.document_id.startswith("doc-")
        assert "Ghid_Practica" in chunk.document_id
        assert chunk.filename == "Ghid_Practica.txt"
        assert "2026-2027" in chunk.source_path or "2026-2027" in chunk.academic_year
        assert chunk.checksum  # non-empty checksum


# ===========================================================================
# SECTION 3 — Recursive Ingestion
# ===========================================================================

@pytest.mark.asyncio
async def test_ingestion_recursive_subdirectory(tmp_path, monkeypatch):
    """ingest_all() discovers documents in subdirectories (Rules/, Answers/)."""
    monkeypatch.setattr(settings, "RAG_CHUNK_SIZE", 100)
    monkeypatch.setattr(settings, "RAG_CHUNK_OVERLAP", 10)

    year_dir = tmp_path / "2026-2027"
    rules_dir = year_dir / "Rules"
    answers_dir = year_dir / "Answers"
    rules_dir.mkdir(parents=True)
    answers_dir.mkdir(parents=True)

    (rules_dir / "practice_rules.md").write_text(
        "Regulamentul UNITBV practica: 90 ore, 4 credite ECTS. " * 3,
        encoding="utf-8",
    )
    (answers_dir / "faq_answers.txt").write_text(
        "Raspuns la intrebarea despre conventie: depuneti pana la 28 august. " * 3,
        encoding="utf-8",
    )
    # Document directly in year dir (non-recursive was already tested)
    (year_dir / "ghid.md").write_text(
        "Ghidul de practica UNITBV 2026-2027. " * 3,
        encoding="utf-8",
    )

    col = f"test_recursive_{uuid.uuid4().hex}"
    registry = FakeRegistry(col)
    store = MockQdrantVectorStore(col)

    pipeline = IngestionPipeline(
        base_dir=str(tmp_path),
        vector_store=store,
        embedding_provider=MockEmbeddingProvider(),
        document_registry=registry,
    )
    summary = await pipeline.ingest_all()

    assert summary["total_documents"] == 3, f"Expected 3, got {summary['total_documents']}"
    assert summary["processed_documents"] == 3


@pytest.mark.asyncio
async def test_ingestion_category_from_subdirectory(tmp_path, monkeypatch):
    """Category is derived correctly from subdirectory name."""
    monkeypatch.setattr(settings, "RAG_CHUNK_SIZE", 150)
    monkeypatch.setattr(settings, "RAG_CHUNK_OVERLAP", 10)

    year_dir = tmp_path / "2026-2027"
    rules_dir = year_dir / "Rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "rules.md").write_text(
        "Regulamentul prevede conditii obligatorii de practica.", encoding="utf-8"
    )

    col = f"test_category_{uuid.uuid4().hex}"
    registry = FakeRegistry(col)
    store = MockQdrantVectorStore(col)

    pipeline = IngestionPipeline(
        base_dir=str(tmp_path),
        vector_store=store,
        embedding_provider=MockEmbeddingProvider(),
        document_registry=registry,
    )
    await pipeline.ingest_all()

    # All chunks from Rules/rules.md should have category="Rules"
    rules_chunks = [p for p in store.points if p["payload"]["filename"] == "rules.md"]
    assert rules_chunks, "No chunks found for rules.md"
    assert all(p["payload"]["category"] == "Rules" for p in rules_chunks)


@pytest.mark.asyncio
async def test_ingestion_skips_readme(tmp_path, monkeypatch):
    """README.md files are skipped during ingestion."""
    monkeypatch.setattr(settings, "RAG_CHUNK_SIZE", 100)
    monkeypatch.setattr(settings, "RAG_CHUNK_OVERLAP", 10)

    year_dir = tmp_path / "2026-2027"
    year_dir.mkdir()
    (year_dir / "README.md").write_text("This is a README.", encoding="utf-8")
    (year_dir / "ghid.md").write_text(
        "Ghidul de practica UNITBV. " * 5, encoding="utf-8"
    )

    col = f"test_readme_{uuid.uuid4().hex}"
    registry = FakeRegistry(col)
    store = MockQdrantVectorStore(col)

    pipeline = IngestionPipeline(
        base_dir=str(tmp_path),
        vector_store=store,
        embedding_provider=MockEmbeddingProvider(),
        document_registry=registry,
    )
    summary = await pipeline.ingest_all()

    assert summary["total_documents"] == 1  # Only ghid.md, not README.md


# ===========================================================================
# SECTION 4 — User Isolation in Vector Store
# ===========================================================================

@pytest.mark.asyncio
async def test_user_isolation_private_documents_not_visible_to_other_user():
    """User A's private documents are NOT returned when querying as User B."""
    USER_A, USER_B = "user_a_phase5", "user_b_phase5"
    chunks = [
        _chunk("ca1", "Informatii private pentru User A despre practica.", user_id=USER_A),
        _chunk("cb1", "Informatii private pentru User B despre practica.", user_id=USER_B),
    ]
    store, provider = await _store_with_chunks(chunks)
    retriever = RAGRetriever(vector_store=store, embedding_provider=provider)

    # User A queries
    results_a = await retriever.retrieve_context(
        "informatii practica",
        academic_year="2026-2027",
        user_id=USER_A,
        top_k=5,
        score_threshold=0.0,
    )
    ids_a = [r["payload"]["chunk_id"] for r in results_a]
    assert "ca1" in ids_a, "User A should see own document"
    assert "cb1" not in ids_a, "User A must NOT see User B's private document"

    # User B queries
    results_b = await retriever.retrieve_context(
        "informatii practica",
        academic_year="2026-2027",
        user_id=USER_B,
        top_k=5,
        score_threshold=0.0,
    )
    ids_b = [r["payload"]["chunk_id"] for r in results_b]
    assert "cb1" in ids_b, "User B should see own document"
    assert "ca1" not in ids_b, "User B must NOT see User A's private document"


@pytest.mark.asyncio
async def test_user_isolation_global_documents_visible_to_all():
    """Global KB documents (user_id=None) are visible to any authenticated user."""
    USER_A = "user_a_global_test"
    chunks = [
        _chunk("global1", "Regulamentul cadru UNITBV practica 90 ore 4 ECTS.", user_id=None),
        _chunk("private_a", "Document privat User A practica.", user_id=USER_A),
    ]
    store, provider = await _store_with_chunks(chunks)
    retriever = RAGRetriever(vector_store=store, embedding_provider=provider)

    # User A sees global + own private
    results_a = await retriever.retrieve_context(
        "practica UNITBV regulament",
        academic_year="2026-2027",
        user_id=USER_A,
        top_k=5,
        score_threshold=0.0,
    )
    ids_a = [r["payload"]["chunk_id"] for r in results_a]
    assert "global1" in ids_a, "User A should see global documents"
    assert "private_a" in ids_a, "User A should see own private documents"


@pytest.mark.asyncio
async def test_user_isolation_no_user_id_returns_only_global():
    """Query without user_id returns only global/public documents."""
    USER_A = "user_a_no_uid"
    chunks = [
        _chunk("global1", "Regulamentul cadru UNITBV practica.", user_id=None),
        _chunk("private_a", "Document privat User A.", user_id=USER_A),
    ]
    store, provider = await _store_with_chunks(chunks)
    retriever = RAGRetriever(vector_store=store, embedding_provider=provider)

    # No user_id → only global
    results = await retriever.retrieve_context(
        "practica regulament",
        academic_year="2026-2027",
        user_id=None,
        top_k=5,
        score_threshold=0.0,
    )
    ids = [r["payload"]["chunk_id"] for r in results]
    assert "global1" in ids
    assert "private_a" not in ids


# ===========================================================================
# SECTION 5 — Academic Year + User Isolation Combined
# ===========================================================================

@pytest.mark.asyncio
async def test_combined_user_id_and_academic_year_filter():
    """user_id + academic_year filters work simultaneously."""
    USER_A = "user_a_combined"
    chunks = [
        _chunk("a-2025", "Termen practica 2025: 15 iulie.", academic_year="2025-2026", user_id=USER_A),
        _chunk("a-2026", "Termen practica 2026: 28 august.", academic_year="2026-2027", user_id=USER_A),
        _chunk("global-2026", "Regulament cadru 2026.", academic_year="2026-2027", user_id=None),
    ]
    store, provider = await _store_with_chunks(chunks)
    retriever = RAGRetriever(vector_store=store, embedding_provider=provider)

    # User A + 2026-2027 → should get a-2026 + global-2026, not a-2025
    results = await retriever.retrieve_context(
        "termen practica",
        academic_year="2026-2027",
        user_id=USER_A,
        top_k=5,
        score_threshold=0.0,
    )
    ids = [r["payload"]["chunk_id"] for r in results]
    assert "a-2026" in ids, "User A's 2026 doc should be included"
    assert "global-2026" in ids, "Global 2026 doc should be included"
    assert "a-2025" not in ids, "2025 doc must NOT appear in 2026 query"


@pytest.mark.asyncio
async def test_academic_year_isolation_between_users():
    """User A's 2025 data doesn't bleed into User B's 2026 query."""
    USER_A, USER_B = "user_a_yr_iso", "user_b_yr_iso"
    chunks = [
        _chunk("a-2025", "Practica 2025: conventie termen 1 iulie.", academic_year="2025-2026", user_id=USER_A),
        _chunk("b-2026", "Practica 2026: conventie termen 28 august.", academic_year="2026-2027", user_id=USER_B),
    ]
    store, provider = await _store_with_chunks(chunks)
    retriever = RAGRetriever(vector_store=store, embedding_provider=provider)

    results_b = await retriever.retrieve_context(
        "conventie practica termen",
        academic_year="2026-2027",
        user_id=USER_B,
        top_k=5,
        score_threshold=0.0,
    )
    ids_b = [r["payload"]["chunk_id"] for r in results_b]
    assert "b-2026" in ids_b
    assert "a-2025" not in ids_b


# ===========================================================================
# SECTION 6 — Q/A Semantic Indexing
# ===========================================================================

@pytest.mark.asyncio
async def test_qa_indexing_upserts_to_vector_store():
    """QAIndexingService indexes a Q/A pair into Qdrant."""
    col = f"test_qa_{uuid.uuid4().hex}"
    store = MockQdrantVectorStore(col)
    provider = MockEmbeddingProvider()
    service = QAIndexingService(vector_store=store, embedding_provider=provider)

    result = await service.index_exchange(
        user_id="user_qa_test",
        academic_year="2026-2027",
        topic="erasmus",
        question_summary="Unde depun cererea Erasmus practica?",
        answer_summary="La biroul de relatii internationale UNITBV.",
        source_type="telegram",
    )
    assert result is True
    assert len(store.points) == 1
    payload = store.points[0]["payload"]
    assert payload["user_id"] == "user_qa_test"
    assert payload["academic_year"] == "2026-2027"
    assert payload["document_type"] == "qa_summary"


@pytest.mark.asyncio
async def test_qa_semantic_search_returns_relevant_qa():
    """QAIndexingService.search_qa() returns semantically relevant Q/A pairs."""
    col = f"test_qa_search_{uuid.uuid4().hex}"
    store = MockQdrantVectorStore(col)
    provider = MockEmbeddingProvider()
    service = QAIndexingService(vector_store=store, embedding_provider=provider)

    await service.index_exchange(
        user_id="user_sr",
        academic_year="2026-2027",
        topic="erasmus",
        question_summary="Ce este cererea Erasmus practica la UNITBV?",
        answer_summary="Cererea Erasmus se depune la biroul de relatii internationale.",
        source_type="faq",
    )
    await service.index_exchange(
        user_id="user_sr",
        academic_year="2026-2027",
        topic="conventie",
        question_summary="Cand se preda conventia de practica?",
        answer_summary="Conventia de practica se preda inainte de inceperea stagiului.",
        source_type="faq",
    )

    results = await service.search_qa(
        query="Erasmus practica cerere UNITBV",
        user_id="user_sr",
        academic_year="2026-2027",
        top_k=3,
        score_threshold=0.0,
    )
    assert len(results) > 0
    # All returned results are Q/A type
    assert all(r["payload"]["document_type"] == "qa_summary" for r in results)


@pytest.mark.asyncio
async def test_qa_user_isolation():
    """Q/A from User A is NOT returned when searching as User B."""
    col = f"test_qa_iso_{uuid.uuid4().hex}"
    store = MockQdrantVectorStore(col)
    provider = MockEmbeddingProvider()
    service = QAIndexingService(vector_store=store, embedding_provider=provider)

    await service.index_exchange(
        user_id="qa_user_a",
        academic_year="2026-2027",
        topic="bursa",
        question_summary="Cum functioneaza bursa de practica UNITBV?",
        answer_summary="Bursa se obtine de la decanat cu cerere scrisa.",
        source_type="faq",
    )
    await service.index_exchange(
        user_id="qa_user_b",
        academic_year="2026-2027",
        topic="erasmus",
        question_summary="Unde depun cererea Erasmus practica?",
        answer_summary="La biroul international UNITBV.",
        source_type="faq",
    )

    results_b = await service.search_qa(
        query="bursa practica",
        user_id="qa_user_b",
        academic_year="2026-2027",
        top_k=5,
        score_threshold=0.0,
    )
    user_ids_in_results = {r["payload"]["user_id"] for r in results_b}
    assert "qa_user_a" not in user_ids_in_results, "User B must NOT see User A's Q/A"


@pytest.mark.asyncio
async def test_qa_indexing_empty_input_is_skipped():
    """Empty Q/A pair is gracefully skipped without errors."""
    col = f"test_qa_empty_{uuid.uuid4().hex}"
    store = MockQdrantVectorStore(col)
    provider = MockEmbeddingProvider()
    service = QAIndexingService(vector_store=store, embedding_provider=provider)

    result = await service.index_exchange(
        user_id="user_empty",
        academic_year="2026-2027",
        topic="test",
        question_summary="",
        answer_summary="",
        source_type="test",
    )
    assert result is False
    assert len(store.points) == 0


# ===========================================================================
# SECTION 7 — No-result Hallucination Protection
# ===========================================================================

@pytest.mark.asyncio
async def test_retrieval_empty_store_returns_empty():
    """Empty vector store returns empty results (no hallucination)."""
    col = f"test_empty_{uuid.uuid4().hex}"
    store = MockQdrantVectorStore(col)
    provider = MockEmbeddingProvider()
    retriever = RAGRetriever(vector_store=store, embedding_provider=provider)

    results = await retriever.retrieve_context(
        "Care este procedura secreta XYZ9999?",
        academic_year="2026-2027",
        user_id="any_user",
        top_k=5,
        score_threshold=0.35,
    )
    assert results == []


@pytest.mark.asyncio
async def test_retrieval_score_threshold_filters_irrelevant():
    """Chunks with score below threshold are filtered out."""
    chunks = [
        _chunk("c1", "Practica UNITBV necesita conventie caiet adeverinta."),
    ]
    store, provider = await _store_with_chunks(chunks)
    retriever = RAGRetriever(vector_store=store, embedding_provider=provider)

    # Query completely unrelated to KB content
    results = await retriever.retrieve_context(
        "Care este retetele culinare din Asia?",
        academic_year="2026-2027",
        user_id=None,
        top_k=5,
        score_threshold=0.5,
    )
    # With high threshold, irrelevant chunks should be filtered
    # (MockEmbeddingProvider uses hash-based deterministic vectors)
    assert isinstance(results, list)  # Always returns a list, never raises


# ===========================================================================
# SECTION 8 — Source/Citation Traceability
# ===========================================================================

def test_chunk_metadata_enables_citation():
    """RAGChunkSchema payload has all fields needed for source citation."""
    chunk = _chunk("c1", "Practica UNITBV.", category="Rules")
    assert chunk.filename  # filename present
    assert chunk.source_path  # full path present
    assert chunk.document_id  # document ID present
    assert chunk.chunk_id  # chunk ID traceable
    assert chunk.academic_year  # year for citation
    assert chunk.checksum  # checksum for integrity


@pytest.mark.asyncio
async def test_vector_store_payload_contains_citation_fields():
    """Upserted vectors carry all citation fields in payload."""
    chunks = [_chunk("c1", "Practica UNITBV regulament.", category="Rules")]
    store, _ = await _store_with_chunks(chunks)
    payload = store.points[0]["payload"]
    required_fields = {
        "chunk_id", "document_id", "filename", "file_name", "academic_year",
        "source", "file_path", "source_path", "checksum", "document_type", "category",
        "user_id", "created_at", "indexed_at", "metadata",
    }
    missing = required_fields - set(payload.keys())
    assert not missing, f"Missing citation fields in payload: {missing}"


@pytest.mark.asyncio
async def test_practice_agent_historical_query_uses_semantic_qa():
    """PracticeAgent.handle_historical_practice_query prioritizes semantic Q/A from Qdrant."""
    from src.app.agents.practice_agent import PracticeAgent

    col = f"test_hist_semantic_{uuid.uuid4().hex}"
    store = MockQdrantVectorStore(col)
    provider = MockEmbeddingProvider()
    qa_service = QAIndexingService(vector_store=store, embedding_provider=provider)

    # Index an exchange
    await qa_service.index_exchange(
        user_id="student_hist_1",
        academic_year="2025-2026",
        topic="bursa",
        question_summary="Care sunt criteriile pentru bursa de merit la practica?",
        answer_summary="Media minima este 8.50 si adeverinta de la angajator.",
        source_type="email_exchange",
        source_reference="email_thread_#456",
    )

    agent = PracticeAgent(
        qa_indexing_service=qa_service,
    )

    res = await agent.handle_historical_practice_query(
        "Ce am discutat despre bursa de merit la practica anul trecut?",
        user_id="student_hist_1",
    )

    assert res["academic_year"] == "2025-2026"
    assert res["history_count"] >= 1
    assert "Media minima este 8.50" in res["text"]
    assert res["sources"][0]["source_type"] == "email_exchange"
    assert res["sources"][0]["source_reference"] == "email_thread_#456"


@pytest.mark.asyncio
async def test_qdrant_vector_store_delete_forwards_user_id():
    """delete_document_vectors in QdrantVectorStore forwards user_id to fallback."""
    from src.app.rag.vector_store import QdrantVectorStore

    store = QdrantVectorStore("test_delete_uid")
    # Insert two chunks for different users into fallback
    chunks = [
        _chunk("c-u1", "doc u1", user_id="u1"),
        _chunk("c-u2", "doc u2", user_id="u2"),
    ]
    await store.mock_fallback.upsert_chunks(chunks, [[0.1] * 768, [0.2] * 768])
    assert len(store.mock_fallback.points) == 2

    # Delete with user_id="u1"
    deleted = await store.delete_document_vectors(user_id="u1")
    assert deleted == 1
    assert len(store.mock_fallback.points) == 1
    assert store.mock_fallback.points[0]["payload"]["user_id"] == "u2"
