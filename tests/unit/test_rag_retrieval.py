import uuid

import pytest

from src.app.rag.embeddings import MockEmbeddingProvider
from src.app.rag.retrieval import RAGRetriever
from src.app.rag.vector_store import MockQdrantVectorStore, QdrantVectorStore
from src.app.schemas.rag import RAGChunkSchema


def _chunk(chunk_id: str, text: str, academic_year: str = "2026-2027") -> RAGChunkSchema:
    return RAGChunkSchema(
        chunk_id=chunk_id,
        document_id=f"doc-{academic_year}-test",
        filename=f"Ghid_Practica_{academic_year}.md",
        academic_year=academic_year,
        page=1,
        chunk_index=0,
        source_path=f"knowledge_base/{academic_year}/Ghid.md",
        text=text,
        checksum=f"checksum-{chunk_id}",
        document_type="md",
    )


async def _store_with_chunks(chunks):
    collection = f"test_retrieval_{uuid.uuid4().hex}"
    provider = MockEmbeddingProvider()
    store = MockQdrantVectorStore(collection)
    vectors = await provider.embed_batch([chunk.text for chunk in chunks])
    await store.upsert_chunks(chunks, vectors)
    return store, provider


@pytest.mark.asyncio
async def test_retrieval_returns_relevant_result():
    chunks = [
        _chunk("c1", "Pentru practica UNITBV sunt necesare conventia, caietul si adeverinta."),
    ]
    store, provider = await _store_with_chunks(chunks)
    retriever = RAGRetriever(vector_store=store, embedding_provider=provider)

    results = await retriever.retrieve_context(
        "Ce documente sunt necesare pentru practica?",
        academic_year="2026-2027",
        top_k=5,
        score_threshold=0.35,
    )

    assert len(results) == 1
    assert results[0]["payload"]["chunk_id"] == "c1"


@pytest.mark.asyncio
async def test_retrieval_filters_irrelevant_query_by_threshold():
    chunks = [
        _chunk("c1", "Pentru practica UNITBV sunt necesare conventia, caietul si adeverinta."),
    ]
    store, provider = await _store_with_chunks(chunks)
    retriever = RAGRetriever(vector_store=store, embedding_provider=provider)

    results = await retriever.retrieve_context(
        "Care este procedura XZY9999?",
        academic_year="2026-2027",
        top_k=5,
        score_threshold=0.35,
    )

    assert results == []


@pytest.mark.asyncio
async def test_retrieval_applies_top_k():
    chunks = [
        _chunk("c1", "Practica UNITBV necesita conventie de practica."),
        _chunk("c2", "Practica UNITBV necesita caiet de practica."),
        _chunk("c3", "Practica UNITBV necesita adeverinta de practica."),
    ]
    store, provider = await _store_with_chunks(chunks)
    retriever = RAGRetriever(vector_store=store, embedding_provider=provider)

    results = await retriever.retrieve_context(
        "Ce necesita practica UNITBV?",
        academic_year="2026-2027",
        top_k=2,
        score_threshold=0.35,
    )

    assert len(results) == 2


@pytest.mark.asyncio
async def test_retrieval_filters_by_academic_year():
    chunks = [
        _chunk("c2025", "Termen practica: 20 august 2025.", academic_year="2025-2026"),
        _chunk("c2026", "Termen practica: 28 august 2026.", academic_year="2026-2027"),
    ]
    store, provider = await _store_with_chunks(chunks)
    retriever = RAGRetriever(vector_store=store, embedding_provider=provider)

    results = await retriever.retrieve_context(
        "Care este termenul pentru practica?",
        academic_year="2025-2026",
        top_k=5,
        score_threshold=0.35,
    )

    assert len(results) == 1
    assert results[0]["payload"]["academic_year"] == "2025-2026"
    assert "2025" in results[0]["payload"]["text"]


@pytest.mark.asyncio
async def test_qdrant_store_uses_query_points_api():
    class FakeQueryResponse:
        def __init__(self):
            self.points = [
                type("Point", (), {"score": 0.91, "payload": {"academic_year": "2026-2027"}})()
            ]

    class FakeClient:
        def query_points(self, **kwargs):
            assert kwargs["query"] == [0.1, 0.2]
            assert kwargs["limit"] == 3
            return FakeQueryResponse()

    store = QdrantVectorStore(collection_name="query_points_contract")
    store.client = FakeClient()
    results = await store.search_similarity(
        query_vector=[0.1, 0.2],
        academic_year="2026-2027",
        top_k=3,
        score_threshold=0.35,
    )

    assert results == [{"score": 0.91, "payload": {"academic_year": "2026-2027"}}]
