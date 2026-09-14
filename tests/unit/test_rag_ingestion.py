import pytest
import uuid
from dataclasses import dataclass
from pathlib import Path
from src.app.rag.chunking import DocumentChunker
from src.app.rag.embeddings import MockEmbeddingProvider
from src.app.rag.vector_store import MockQdrantVectorStore
from src.app.rag.ingestion import IngestionPipeline
from src.app.rag.document_registry import PracticeDocumentRecord
from src.app.core.config import settings


PDF_WITH_TEXT = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>
endobj
4 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
5 0 obj
<< /Length 91 >>
stream
BT /F1 12 Tf 72 720 Td (Practica UNITBV PDF test documente necesare 2026-2027) Tj ET
endstream
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000241 00000 n 
0000000311 00000 n 
trailer
<< /Size 6 /Root 1 0 R >>
startxref
452
%%EOF
"""


class FakePracticeDocumentRegistry:
    def __init__(self, collection_name: str):
        self.collection_name = collection_name
        self.records = {}

    async def get_document(self, file_path: Path, academic_year: str):
        return self.records.get(self._key(file_path, academic_year))

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
        self.records[self._key(kwargs["file_path"], kwargs["academic_year"])] = record
        return record

    async def mark_failed(self, **kwargs):
        kwargs["chunks_count"] = 0
        kwargs["vectors_count"] = 0
        kwargs["status"] = "failed"
        kwargs["metadata"] = {"error": kwargs.get("error", "")}
        return await self.mark_processed(**kwargs)

    def _key(self, file_path: Path, academic_year: str):
        return (academic_year, str(file_path.resolve()), self.collection_name)


def test_text_cleaning_and_chunking():
    chunker = DocumentChunker(chunk_size=100, chunk_overlap=20)
    sample_text = "Acesta este un document de test pentru practica studențească UNITBV.\n\nContine regulamente si termene."
    cleaned = chunker.clean_text(sample_text)
    assert "\n\n" in cleaned
    assert "  " not in cleaned


def test_chunking_stops_after_the_terminal_fragment(tmp_path):
    year_dir = tmp_path / "2026-2027"
    year_dir.mkdir()
    document = year_dir / "terminal.txt"
    document.write_text("x" * 1_000, encoding="utf-8")

    chunks = DocumentChunker(chunk_size=800, chunk_overlap=100).chunk_document(
        document,
        academic_year="2026-2027",
    )

    assert len(chunks) == 2
    assert len(chunks[-1].text) == 300


@pytest.mark.asyncio
async def test_mock_embedding_provider():
    provider = MockEmbeddingProvider()
    vec = await provider.embed_text("Practică UNITBV 2026-2027")
    assert len(vec) == settings.EMBEDDING_VECTOR_SIZE
    # Verify vector normalization
    assert abs(sum(x * x for x in vec) - 1.0) < 1e-4


@pytest.mark.asyncio
async def test_mock_qdrant_vector_store():
    store = MockQdrantVectorStore()
    await store.init_collection(vector_size=settings.EMBEDDING_VECTOR_SIZE)
    assert store.collection_name == "practice_knowledge"


def test_pdf_text_extraction(tmp_path):
    pdf_path = tmp_path / "Ghid_Practica_Test.pdf"
    pdf_path.write_bytes(PDF_WITH_TEXT)

    chunker = DocumentChunker(chunk_size=120, chunk_overlap=20)
    pages = chunker.extract_text_from_file(pdf_path)

    assert pages
    assert pages[0][0] == 1
    assert "Practica UNITBV PDF test" in pages[0][1]


@pytest.mark.asyncio
async def test_ingestion_skips_duplicate_with_persistent_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "RAG_CHUNK_SIZE", 120)
    monkeypatch.setattr(settings, "RAG_CHUNK_OVERLAP", 20)

    year_dir = tmp_path / "2026-2027"
    year_dir.mkdir()
    document = year_dir / "Ghid_Practica.md"
    document.write_text("Practica UNITBV are documente necesare si termene clare pentru studenti.", encoding="utf-8")

    collection = f"test_practice_{uuid.uuid4().hex}"
    registry = FakePracticeDocumentRegistry(collection)
    store = MockQdrantVectorStore(collection)

    first = IngestionPipeline(
        base_dir=str(tmp_path),
        vector_store=store,
        embedding_provider=MockEmbeddingProvider(),
        document_registry=registry,
    )
    first_summary = await first.ingest_all()

    second = IngestionPipeline(
        base_dir=str(tmp_path),
        vector_store=MockQdrantVectorStore(collection),
        embedding_provider=MockEmbeddingProvider(),
        document_registry=registry,
    )
    second_summary = await second.ingest_all()

    assert first_summary["processed_documents"] == 1
    assert second_summary["processed_documents"] == 0
    assert second_summary["skipped_documents"] == 1


@pytest.mark.asyncio
async def test_ingestion_reprocesses_modified_document_and_removes_old_vectors(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "RAG_CHUNK_SIZE", 90)
    monkeypatch.setattr(settings, "RAG_CHUNK_OVERLAP", 10)

    year_dir = tmp_path / "2026-2027"
    year_dir.mkdir()
    document = year_dir / "Regulament_Practica.txt"
    document.write_text(
        "Practica UNITBV versiune veche cu documente initiale. " * 4,
        encoding="utf-8",
    )

    collection = f"test_practice_{uuid.uuid4().hex}"
    registry = FakePracticeDocumentRegistry(collection)
    store = MockQdrantVectorStore(collection)

    pipeline = IngestionPipeline(
        base_dir=str(tmp_path),
        vector_store=store,
        embedding_provider=MockEmbeddingProvider(),
        document_registry=registry,
    )
    await pipeline.ingest_all()
    old_checksum = next(iter(registry.records.values())).checksum

    document.write_text(
        "Practica UNITBV versiune noua cu termen final actualizat si caiet de practica.",
        encoding="utf-8",
    )

    reprocess = IngestionPipeline(
        base_dir=str(tmp_path),
        vector_store=MockQdrantVectorStore(collection),
        embedding_provider=MockEmbeddingProvider(),
        document_registry=registry,
    )
    summary = await reprocess.ingest_all()
    new_record = next(iter(registry.records.values()))

    assert summary["processed_documents"] == 1
    assert new_record.checksum != old_checksum
    assert all(point["payload"]["checksum"] == new_record.checksum for point in store.points)
    assert all("versiune veche" not in point["payload"]["text"] for point in store.points)


@pytest.mark.asyncio
async def test_ingestion_reprocesses_when_chunking_profile_changes(tmp_path, monkeypatch):
    year_dir = tmp_path / "2026-2027"
    year_dir.mkdir()
    document = year_dir / "Regulament_Practica.txt"
    document.write_text("Practica UNITBV are documente necesare si termene clare. " * 20, encoding="utf-8")

    collection = f"test_practice_{uuid.uuid4().hex}"
    registry = FakePracticeDocumentRegistry(collection)
    store = MockQdrantVectorStore(collection)

    monkeypatch.setattr(settings, "RAG_CHUNK_SIZE", 120)
    monkeypatch.setattr(settings, "RAG_CHUNK_OVERLAP", 20)
    first = IngestionPipeline(
        base_dir=str(tmp_path),
        vector_store=store,
        embedding_provider=MockEmbeddingProvider(),
        document_registry=registry,
    )
    await first.ingest_all()
    first_vector_count = len(store.points)

    monkeypatch.setattr(settings, "RAG_CHUNK_SIZE", 240)
    second = IngestionPipeline(
        base_dir=str(tmp_path),
        vector_store=MockQdrantVectorStore(collection),
        embedding_provider=MockEmbeddingProvider(),
        document_registry=registry,
    )
    summary = await second.ingest_all()

    assert summary["processed_documents"] == 1
    assert len(store.points) < first_vector_count
