from pathlib import Path
from typing import List, Dict, Any, Optional
from src.app.rag.chunking import DocumentChunker
from src.app.rag.embeddings import get_embedding_provider, EmbeddingProvider
from src.app.rag.vector_store import QdrantVectorStore
from src.app.rag.document_registry import PracticeDocumentRegistry
from src.app.core.config import settings
from src.app.core.logging import logger


class IngestionPipeline:
    """
    RAG Ingestion Pipeline. Scans knowledge base directories, extracts text,
    chunks documents, generates embeddings, and upserts vectors into Qdrant.
    """

    def __init__(
        self,
        base_dir: Optional[str] = None,
        vector_store: Optional[QdrantVectorStore] = None,
        embedding_provider: Optional[EmbeddingProvider] = None,
        document_registry: Optional[PracticeDocumentRegistry] = None,
    ):
        self.base_dir = Path(base_dir or settings.KNOWLEDGE_BASE_DIR)
        self.chunker = DocumentChunker(
            chunk_size=settings.RAG_CHUNK_SIZE,
            chunk_overlap=settings.RAG_CHUNK_OVERLAP,
        )
        self.embedding_provider = embedding_provider or get_embedding_provider()
        self.vector_store = vector_store or QdrantVectorStore()
        self.document_registry = document_registry or PracticeDocumentRegistry(
            collection_name=self.vector_store.collection_name
        )

    def _ingestion_profile(self) -> Dict[str, Any]:
        """Describe settings that affect vectors and therefore require re-ingestion."""
        return {
            "chunk_size": settings.RAG_CHUNK_SIZE,
            "chunk_overlap": settings.RAG_CHUNK_OVERLAP,
            "embedding_provider": settings.EMBEDDING_PROVIDER.lower(),
            "embedding_model": getattr(self.embedding_provider, "model", settings.EMBEDDING_MODEL),
            "embedding_vector_size": settings.EMBEDDING_VECTOR_SIZE,
        }

    async def ingest_all(self) -> Dict[str, Any]:
        """
        Scans all academic year subdirectories RECURSIVELY and ingests new or modified documents.
        Directory structure:
          knowledge_base/
            <academic_year>/       e.g. 2026-2027/, general/
              [sub-category/]      e.g. Rules/, Answers/ (optional; any depth)
                document.pdf|txt|md
        The academic_year is extracted from the top-level subdirectory name.
        The category is derived from the relative path of the file within year_dir.
        """
        await self.vector_store.init_collection(vector_size=settings.EMBEDDING_VECTOR_SIZE)

        if not self.base_dir.exists():
            logger.warning(f"Knowledge Base directory '{self.base_dir}' does not exist.")
            return {"status": "error", "message": "Knowledge base directory missing"}

        academic_year_dirs = [d for d in self.base_dir.iterdir() if d.is_dir()]
        total_docs = 0
        processed_docs = 0
        skipped_docs = 0
        total_chunks = 0
        total_vectors = 0
        ingestion_profile = self._ingestion_profile()

        SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md"}
        SKIP_FILENAMES = {"README.md", "README.txt"}

        for year_dir in academic_year_dirs:
            academic_year = year_dir.name  # e.g. "2026-2027" or "general"

            # Recursive discovery: find all supported documents at any depth
            files = [
                f for f in year_dir.rglob("*")
                if f.is_file()
                and f.suffix.lower() in SUPPORTED_EXTENSIONS
                and f.name not in SKIP_FILENAMES
            ]

            for file_path in files:
                total_docs += 1
                checksum = DocumentChunker.compute_file_checksum(file_path)
                document_id = DocumentChunker.build_document_id(file_path, academic_year)
                document_type = file_path.suffix.lstrip(".").lower()

                # Derive category from relative path within year_dir.
                # e.g. year_dir/Rules/doc.pdf → category = "Rules"
                # e.g. year_dir/doc.pdf → category = "general"
                relative_parts = file_path.relative_to(year_dir).parts
                category = relative_parts[0] if len(relative_parts) > 1 else "general"

                previous = await self.document_registry.get_document(file_path, academic_year)

                # Skip unchanged files
                previous_profile = (previous.metadata or {}).get("ingestion_profile") if previous else None
                if (
                    previous
                    and previous.checksum == checksum
                    and previous.status == "processed"
                    and previous_profile == ingestion_profile
                ):
                    logger.info(f"Skipping unchanged document: '{file_path.name}' ({academic_year}/{category})")
                    skipped_docs += 1
                    continue

                try:
                    if previous and previous.checksum != checksum:
                        logger.info(f"Detected modified document: '{file_path.name}' ({academic_year}); removing stale vectors.")
                        await self.vector_store.delete_document_vectors(
                            document_id=previous.document_id,
                            academic_year=academic_year,
                            source_path=str(file_path),
                        )

                    # Clean any stale chunks for this path before upsert
                    await self.vector_store.delete_document_vectors(
                        document_id=document_id,
                        academic_year=academic_year,
                        source_path=str(file_path),
                    )

                    chunks = self.chunker.chunk_document(
                        file_path,
                        academic_year=academic_year,
                        category=category,
                    )
                    if not chunks:
                        await self.document_registry.mark_failed(
                            document_id=document_id,
                            file_path=file_path,
                            academic_year=academic_year,
                            checksum=checksum,
                            document_type=document_type,
                            error="No extractable text or chunks produced",
                        )
                        skipped_docs += 1
                        continue

                    texts = [c.text for c in chunks]
                    vectors = await self.embedding_provider.embed_batch(texts)
                    if len(vectors) != len(chunks):
                        raise ValueError(
                            f"Embedding provider returned {len(vectors)} vectors for {len(chunks)} chunks"
                        )
                    if any(len(vector) != settings.EMBEDDING_VECTOR_SIZE for vector in vectors):
                        actual_size = next(len(vector) for vector in vectors if len(vector) != settings.EMBEDDING_VECTOR_SIZE)
                        raise ValueError(
                            f"Embedding size mismatch: configured {settings.EMBEDDING_VECTOR_SIZE}, got {actual_size}"
                        )

                    upsert_count = await self.vector_store.upsert_chunks(chunks, vectors)
                    await self.document_registry.mark_processed(
                        document_id=document_id,
                        file_path=file_path,
                        academic_year=academic_year,
                        checksum=checksum,
                        document_type=document_type,
                        chunks_count=len(chunks),
                        vectors_count=upsert_count,
                        metadata={
                            "source_path": str(file_path),
                            "category": category,
                            "file_size_bytes": file_path.stat().st_size,
                            "ingestion_profile": ingestion_profile,
                        },
                    )

                    processed_docs += 1
                    total_chunks += len(chunks)
                    total_vectors += upsert_count
                    logger.info(
                        f"Ingested '{file_path.name}' ({academic_year}/{category}): {len(chunks)} chunks."
                    )
                except Exception as e:
                    logger.error("Error ingesting document '%s' (%s).", file_path.name, type(e).__name__)
                    await self.document_registry.mark_failed(
                        document_id=document_id,
                        file_path=file_path,
                        academic_year=academic_year,
                        checksum=checksum,
                        document_type=document_type,
                        error=f"Ingestion failed: {type(e).__name__}",
                    )
                    skipped_docs += 1

        summary = {
            "status": "success",
            "total_documents": total_docs,
            "processed_documents": processed_docs,
            "skipped_documents": skipped_docs,
            "total_chunks": total_chunks,
            "upserted_vectors": total_vectors
        }

        logger.info(f"Ingestion completed: {summary}")
        return summary
