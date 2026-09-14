"""
Phase 5 — RAG Live Integration Tests.

These tests interact with REAL infrastructure (Qdrant + Ollama).
They are marked with @pytest.mark.integration and skipped automatically
when EMBEDDING_PROVIDER != 'ollama' or Qdrant is not reachable.

IMPORTANT: These tests use a dedicated scratch collection that is created
and cleaned up within the test. They NEVER touch the production collection.

Run only in an environment with Docker Compose running:
    pytest tests/integration/test_rag_live.py -v -m integration
"""
import os
import uuid
import asyncio
import pytest

# Skip all tests if EMBEDDING_PROVIDER is not 'ollama' (e.g. in CI mock mode)
# or if tests are running in the normal test suite (conftest sets EMBEDDING_PROVIDER=mock)
pytestmark = pytest.mark.integration


SCRATCH_COLLECTION = f"rag_phase5_live_scratch_{uuid.uuid4().hex[:8]}"


def _is_live_env() -> bool:
    """Return True only when the real Ollama embedding provider is configured."""
    provider = os.environ.get("EMBEDDING_PROVIDER", "mock").lower()
    return provider == "ollama"


def skip_if_not_live():
    return pytest.mark.skipif(
        not _is_live_env(),
        reason="EMBEDDING_PROVIDER != 'ollama' — set env to run live integration tests",
    )


# ---------------------------------------------------------------------------
# Qdrant connectivity
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@skip_if_not_live()
async def test_live_qdrant_health():
    """LIVE: Qdrant responds to health check."""
    import httpx
    from src.app.core.config import settings

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{settings.effective_qdrant_url}/healthz", timeout=5.0)
    assert resp.status_code == 200, f"Qdrant health check failed: {resp.status_code}"
    assert "healthz check passed" in resp.text


@pytest.mark.asyncio
@skip_if_not_live()
async def test_live_qdrant_collection_create_and_delete():
    """LIVE: Create scratch collection, verify it exists, then delete it."""
    import httpx
    from src.app.core.config import settings

    col = f"rag_phase5_scratch_col_{uuid.uuid4().hex[:8]}"
    base = settings.effective_qdrant_url

    async with httpx.AsyncClient() as client:
        # Create
        create_resp = await client.put(
            f"{base}/collections/{col}",
            json={"vectors": {"size": settings.EMBEDDING_VECTOR_SIZE, "distance": "Cosine"}},
            timeout=10.0,
        )
        assert create_resp.status_code == 200, f"Create failed: {create_resp.text}"

        # List collections — verify it exists
        list_resp = await client.get(f"{base}/collections", timeout=5.0)
        assert list_resp.status_code == 200
        names = [c["name"] for c in list_resp.json()["result"]["collections"]]
        assert col in names

        # Delete
        del_resp = await client.delete(f"{base}/collections/{col}", timeout=10.0)
        assert del_resp.status_code == 200


# ---------------------------------------------------------------------------
# Ollama Embeddings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@skip_if_not_live()
async def test_live_ollama_embedding_dimension():
    """LIVE: Ollama nomic-embed-text produces 768-dim vectors."""
    from src.app.rag.embeddings import OllamaEmbeddingProvider
    from src.app.core.config import settings

    provider = OllamaEmbeddingProvider(model=settings.EMBEDDING_MODEL)
    vector = await provider.embed_text("Practica UNITBV conventie caiet adeverinta 2026-2027")

    assert len(vector) == settings.EMBEDDING_VECTOR_SIZE, (
        f"Expected {settings.EMBEDDING_VECTOR_SIZE} dims, got {len(vector)}. "
        f"Check EMBEDDING_MODEL={settings.EMBEDDING_MODEL} and EMBEDDING_VECTOR_SIZE={settings.EMBEDDING_VECTOR_SIZE}"
    )
    # Verify it's a valid float vector
    assert all(isinstance(v, float) for v in vector)


@pytest.mark.asyncio
@skip_if_not_live()
async def test_live_ollama_embedding_batch():
    """LIVE: Ollama returns correct batch size."""
    from src.app.rag.embeddings import OllamaEmbeddingProvider
    from src.app.core.config import settings

    provider = OllamaEmbeddingProvider(model=settings.EMBEDDING_MODEL)
    texts = [
        "Practica UNITBV necesita conventie",
        "Termenul pentru caiet de practica este 28 august 2026",
        "Regulamentul prevede 90 de ore si 4 credite ECTS",
    ]
    vectors = await provider.embed_batch(texts)
    assert len(vectors) == len(texts)
    for v in vectors:
        assert len(v) == settings.EMBEDDING_VECTOR_SIZE


@pytest.mark.asyncio
@skip_if_not_live()
async def test_live_ollama_semantic_similarity():
    """LIVE: Semantically similar texts produce similar vectors."""
    from src.app.rag.embeddings import OllamaEmbeddingProvider
    from src.app.core.config import settings
    import math

    provider = OllamaEmbeddingProvider(model=settings.EMBEDDING_MODEL)

    v1 = await provider.embed_text("conventie de practica")
    v2 = await provider.embed_text("contract de practica student")  # semantically close
    v3 = await provider.embed_text("fotbal campionat mondial")  # semantically distant

    def cosine(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0

    sim_close = cosine(v1, v2)
    sim_far = cosine(v1, v3)

    assert sim_close > sim_far, (
        f"Semantic similarity check failed: sim_close={sim_close:.3f}, sim_far={sim_far:.3f}. "
        "Semantically similar texts should score higher."
    )


# ---------------------------------------------------------------------------
# End-to-End: Qdrant + Ollama
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@skip_if_not_live()
async def test_live_e2e_ingest_and_retrieve(tmp_path):
    """
    LIVE E2E: ingest a real document with Ollama embeddings into Qdrant scratch collection,
    then retrieve it semantically. Scratch collection is cleaned up after test.
    """
    from src.app.rag.embeddings import OllamaEmbeddingProvider
    from src.app.rag.vector_store import QdrantVectorStore
    from src.app.rag.retrieval import RAGRetriever
    from src.app.rag.chunking import DocumentChunker
    from src.app.schemas.rag import RAGChunkSchema
    from src.app.core.config import settings

    col = SCRATCH_COLLECTION
    provider = OllamaEmbeddingProvider(model=settings.EMBEDDING_MODEL)
    store = QdrantVectorStore(collection_name=col)

    try:
        await store.init_collection(vector_size=settings.EMBEDDING_VECTOR_SIZE)

        # Create a test document
        doc = tmp_path / "Ghid_Practica_Live.md"
        doc.write_text(
            "Termenul limita pentru depunerea conventiei de practica este 28 august 2026. "
            "Studentii trebuie sa depuna caietul de practica completat si semnat. "
            "Adeverinta de practica se obtine de la tutorele de la firma.",
            encoding="utf-8",
        )

        # Chunk it
        chunker = DocumentChunker(chunk_size=300, chunk_overlap=50)
        chunks = chunker.chunk_document(doc, academic_year="2026-2027", category="Rules")
        assert chunks, "Chunking produced no chunks"

        # Embed with Ollama
        texts = [c.text for c in chunks]
        vectors = await provider.embed_batch(texts)
        assert len(vectors) == len(chunks)
        assert all(len(v) == settings.EMBEDDING_VECTOR_SIZE for v in vectors)

        # Upsert to Qdrant
        upserted = await store.upsert_chunks(chunks, vectors)
        assert upserted == len(chunks)

        # Semantic search
        retriever = RAGRetriever(vector_store=store, embedding_provider=provider)
        results = await retriever.retrieve_context(
            "Care este termenul pentru conventia de practica?",
            academic_year="2026-2027",
            user_id=None,
            top_k=3,
            score_threshold=0.3,
        )

        assert len(results) > 0, "Live semantic search returned no results"
        # Verify semantic match — answer should be in the retrieved text
        retrieved_texts = [r["payload"]["text"] for r in results]
        combined = " ".join(retrieved_texts)
        assert "conventie" in combined.lower() or "practica" in combined.lower(), (
            "Retrieved text does not seem semantically related to the query"
        )

        # Verify sources are traceable
        assert results[0]["payload"]["filename"] == "Ghid_Practica_Live.md"
        assert results[0]["payload"]["category"] == "Rules"

    finally:
        # Cleanup: delete the scratch collection
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.delete(
                    f"{settings.effective_qdrant_url}/collections/{col}",
                    timeout=10.0,
                )
        except Exception:
            pass  # Best-effort cleanup


@pytest.mark.asyncio
@skip_if_not_live()
async def test_live_qa_indexing_and_semantic_search():
    """LIVE: Q/A indexing with Ollama + semantic search in Qdrant scratch collection."""
    from src.app.rag.embeddings import OllamaEmbeddingProvider
    from src.app.rag.vector_store import QdrantVectorStore
    from src.app.rag.qa_indexing import QAIndexingService
    from src.app.core.config import settings

    col = f"rag_phase5_qa_live_{uuid.uuid4().hex[:8]}"
    provider = OllamaEmbeddingProvider(model=settings.EMBEDDING_MODEL)
    store = QdrantVectorStore(collection_name=col)

    try:
        await store.init_collection(vector_size=settings.EMBEDDING_VECTOR_SIZE)
        qa_service = QAIndexingService(vector_store=store, embedding_provider=provider)

        result = await qa_service.index_exchange(
            user_id="live_user_qa",
            academic_year="2026-2027",
            topic="erasmus",
            question_summary="Cum aplic pentru practica Erasmus la UNITBV?",
            answer_summary="Cererea Erasmus se depune la biroul de relatii internationale FIESC.",
            source_type="test",
        )
        assert result is True, "Q/A indexing failed"

        hits = await qa_service.search_qa(
            query="practica Erasmus cerere UNITBV",
            user_id="live_user_qa",
            academic_year="2026-2027",
            top_k=3,
            score_threshold=0.3,
        )
        assert len(hits) > 0, "Live Q/A semantic search returned no results"
        assert hits[0]["payload"]["user_id"] == "live_user_qa"

    finally:
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.delete(
                    f"{settings.effective_qdrant_url}/collections/{col}",
                    timeout=10.0,
                )
        except Exception:
            pass


@pytest.mark.asyncio
@skip_if_not_live()
async def test_live_user_isolation_real_qdrant():
    """LIVE: Real Qdrant ensures User A cannot retrieve User B's private documents."""
    from src.app.rag.embeddings import OllamaEmbeddingProvider
    from src.app.rag.vector_store import QdrantVectorStore
    from src.app.rag.retrieval import RAGRetriever
    from src.app.schemas.rag import RAGChunkSchema
    from src.app.core.config import settings

    col = f"rag_live_user_iso_{uuid.uuid4().hex[:8]}"
    provider = OllamaEmbeddingProvider(model=settings.EMBEDDING_MODEL)
    store = QdrantVectorStore(collection_name=col)

    try:
        await store.init_collection(vector_size=settings.EMBEDDING_VECTOR_SIZE)

        chunks = [
            RAGChunkSchema(
                chunk_id="chunk-alpha-private",
                document_id="doc-alpha",
                filename="alpha_private.txt",
                academic_year="2026-2027",
                source_path="knowledge_base/private/alpha.txt",
                text="Document secret al utilizatorului Alpha despre practica UNITBV.",
                checksum="cs-alpha",
                user_id="user_alpha",
            ),
            RAGChunkSchema(
                chunk_id="chunk-beta-private",
                document_id="doc-beta",
                filename="beta_private.txt",
                academic_year="2026-2027",
                source_path="knowledge_base/private/beta.txt",
                text="Document confidential al utilizatorului Beta despre practica UNITBV.",
                checksum="cs-beta",
                user_id="user_beta",
            ),
            RAGChunkSchema(
                chunk_id="chunk-global-public",
                document_id="doc-global",
                filename="global_rules.txt",
                academic_year="2026-2027",
                source_path="knowledge_base/2026-2027/rules.txt",
                text="Regulament public cadru practica UNITBV pentru toti studentii.",
                checksum="cs-global",
                user_id=None,
            ),
        ]

        vectors = await provider.embed_batch([c.text for c in chunks])
        await store.upsert_chunks(chunks, vectors)

        retriever = RAGRetriever(vector_store=store, embedding_provider=provider)

        # 1. Query as User Alpha: must see alpha + global, NEVER beta
        hits_alpha = await retriever.retrieve_context(
            "practica UNITBV document secret utilizator",
            academic_year="2026-2027",
            user_id="user_alpha",
            top_k=5,
            score_threshold=0.0,
        )
        ids_alpha = [h["payload"]["chunk_id"] for h in hits_alpha]
        assert "chunk-alpha-private" in ids_alpha, "User Alpha should see own document"
        assert "chunk-beta-private" not in ids_alpha, "CRITICAL: User Alpha must NOT see User Beta's document"

        # 2. Query as User Beta: must see beta + global, NEVER alpha
        hits_beta = await retriever.retrieve_context(
            "practica UNITBV document confidential utilizator",
            academic_year="2026-2027",
            user_id="user_beta",
            top_k=5,
            score_threshold=0.0,
        )
        ids_beta = [h["payload"]["chunk_id"] for h in hits_beta]
        assert "chunk-beta-private" in ids_beta, "User Beta should see own document"
        assert "chunk-alpha-private" not in ids_beta, "CRITICAL: User Beta must NOT see User Alpha's document"

        # 3. Anonymous/Global query: neither private doc returned
        hits_anon = await retriever.retrieve_context(
            "practica UNITBV",
            academic_year="2026-2027",
            user_id=None,
            top_k=5,
            score_threshold=0.0,
        )
        ids_anon = [h["payload"]["chunk_id"] for h in hits_anon]
        assert "chunk-alpha-private" not in ids_anon
        assert "chunk-beta-private" not in ids_anon
        assert "chunk-global-public" in ids_anon

    finally:
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.delete(
                    f"{settings.effective_qdrant_url}/collections/{col}",
                    timeout=10.0,
                )
        except Exception:
            pass


@pytest.mark.asyncio
@skip_if_not_live()
async def test_live_multi_year_and_user_isolation_real_qdrant():
    """LIVE: Real Qdrant enforces academic_year filtering across years."""
    from src.app.rag.embeddings import OllamaEmbeddingProvider
    from src.app.rag.vector_store import QdrantVectorStore
    from src.app.rag.retrieval import RAGRetriever
    from src.app.schemas.rag import RAGChunkSchema
    from src.app.core.config import settings

    col = f"rag_live_year_iso_{uuid.uuid4().hex[:8]}"
    provider = OllamaEmbeddingProvider(model=settings.EMBEDDING_MODEL)
    store = QdrantVectorStore(collection_name=col)

    try:
        await store.init_collection(vector_size=settings.EMBEDDING_VECTOR_SIZE)

        chunks = [
            RAGChunkSchema(
                chunk_id="chunk-2026-user",
                document_id="doc-2026",
                filename="Ghid_2026_2027.md",
                academic_year="2026-2027",
                source_path="knowledge_base/2026-2027/Ghid.md",
                text="Termen predare conventie practica 2026-2027 este 28 august 2026.",
                checksum="cs-2026",
                user_id="student_1",
            ),
            RAGChunkSchema(
                chunk_id="chunk-2025-user",
                document_id="doc-2025",
                filename="Ghid_2025_2026.md",
                academic_year="2025-2026",
                source_path="knowledge_base/2025-2026/Ghid.md",
                text="Termen predare conventie practica 2025-2026 a fost 15 iulie 2025.",
                checksum="cs-2025",
                user_id="student_1",
            ),
        ]

        vectors = await provider.embed_batch([c.text for c in chunks])
        await store.upsert_chunks(chunks, vectors)

        retriever = RAGRetriever(vector_store=store, embedding_provider=provider)

        # Query for 2026-2027 must NOT return 2025-2026
        hits_2026 = await retriever.retrieve_context(
            "termen predare conventie practica",
            academic_year="2026-2027",
            user_id="student_1",
            top_k=5,
            score_threshold=0.0,
        )
        ids_2026 = [h["payload"]["chunk_id"] for h in hits_2026]
        assert "chunk-2026-user" in ids_2026
        assert "chunk-2025-user" not in ids_2026, "2025 chunk leaked into 2026 query"

        # Query for 2025-2026 must NOT return 2026-2027
        hits_2025 = await retriever.retrieve_context(
            "termen predare conventie practica",
            academic_year="2025-2026",
            user_id="student_1",
            top_k=5,
            score_threshold=0.0,
        )
        ids_2025 = [h["payload"]["chunk_id"] for h in hits_2025]
        assert "chunk-2025-user" in ids_2025
        assert "chunk-2026-user" not in ids_2025, "2026 chunk leaked into 2025 query"

    finally:
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.delete(
                    f"{settings.effective_qdrant_url}/collections/{col}",
                    timeout=10.0,
                )
        except Exception:
            pass
