import asyncio
import uuid
import re
import unicodedata
from typing import List, Dict, Any, Optional
from src.app.schemas.rag import RAGChunkSchema
from src.app.core.config import settings
from src.app.core.logging import logger
from src.app.core.exceptions import RAGRetrievalException


class MockQdrantVectorStore:
    """
    In-memory fallback vector store used for unit tests and local execution when Qdrant container is offline.
    """

    _collections: Dict[str, List[Dict[str, Any]]] = {}
    _stopwords = {
        "a", "ai", "al", "ale", "am", "an", "anul", "asta", "care", "ce",
        "cu", "cum", "de", "din", "este", "fac", "face", "fara", "in", "la",
        "mai", "pentru", "pe", "procedura", "sau", "se", "sunt", "si", "un",
        "universitar",
    }

    def __init__(self, collection_name: str = "practice_knowledge"):
        self.collection_name = collection_name
        self.points = self._collections.setdefault(collection_name, [])

    async def init_collection(self, vector_size: int = 1536):
        logger.info(f"[MockQdrantVectorStore] Initialized collection '{self.collection_name}' (dim={vector_size}).")

    async def upsert_chunks(self, chunks: List[RAGChunkSchema], vectors: List[List[float]]) -> int:
        for chunk, vector in zip(chunks, vectors):
            payload = {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "filename": chunk.filename,
                "academic_year": chunk.academic_year,
                "page": chunk.page,
                "chunk_index": chunk.chunk_index,
                "source_path": chunk.source_path,
                "text": chunk.text,
                "checksum": chunk.checksum,
                "document_type": chunk.document_type
            }
            # Remove existing chunk with same chunk_id before upsert.
            self.points[:] = [p for p in self.points if p["payload"]["chunk_id"] != chunk.chunk_id]
            self.points.append({"id": chunk.chunk_id, "vector": vector, "payload": payload})

        logger.info(f"[MockQdrantVectorStore] Upserted {len(chunks)} vectors to '{self.collection_name}'. Total: {len(self.points)}")
        return len(chunks)

    async def search_similarity(
        self,
        query_vector: List[float],
        academic_year: Optional[str] = None,
        top_k: int = 5,
        score_threshold: float = 0.35,
        query_text: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        results = []
        query_tokens = self._tokens(query_text or "")
        for item in self.points:
            payload = item["payload"]
            # Academic year filter
            if academic_year:
                chunk_year = payload.get("academic_year")
                if academic_year == "general":
                    if chunk_year != "general":
                        continue
                else:
                    if chunk_year != academic_year and chunk_year != "general":
                        continue

            # Compute cosine similarity
            v = item["vector"]
            dot_prod = sum(a * b for a, b in zip(query_vector, v))

            score = self._score_payload(
                query_tokens=query_tokens,
                payload=payload,
                vector_score=max(0.0, dot_prod),
            )
            
            if score >= score_threshold:
                results.append({
                    "score": score,
                    "payload": payload
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    async def delete_document_vectors(
        self,
        document_id: Optional[str] = None,
        academic_year: Optional[str] = None,
        source_path: Optional[str] = None,
        checksum: Optional[str] = None,
    ) -> int:
        before = len(self.points)

        def should_delete(item: Dict[str, Any]) -> bool:
            payload = item["payload"]
            checks = []
            if document_id:
                checks.append(payload.get("document_id") == document_id)
            if academic_year:
                checks.append(payload.get("academic_year") == academic_year)
            if source_path:
                checks.append(payload.get("source_path") == source_path)
            if checksum:
                checks.append(payload.get("checksum") == checksum)
            return bool(checks) and all(checks)

        self.points[:] = [p for p in self.points if not should_delete(p)]
        deleted = before - len(self.points)
        logger.info(f"[MockQdrantVectorStore] Deleted {deleted} vectors from '{self.collection_name}'.")
        return deleted

    @classmethod
    def _tokens(cls, text: str) -> set:
        normalized = unicodedata.normalize("NFKD", text.lower())
        ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        raw_tokens = re.findall(r"[a-z0-9]+", ascii_text)
        tokens = set()
        for token in raw_tokens:
            if len(token) < 3 or token in cls._stopwords:
                continue
            tokens.add(cls._stem_token(token))
        return tokens

    @staticmethod
    def _stem_token(token: str) -> str:
        stems = {
            "practic": "practica",
            "convent": "conventie",
            "document": "document",
            "necesar": "necesar",
            "termen": "termen",
            "deadline": "termen",
            "colocv": "colocviu",
            "caiet": "caiet",
            "adever": "adeverinta",
            "erasmus": "erasmus",
            "regul": "regulament",
            "desfasur": "desfasurare",
            "evalu": "evaluare",
        }
        for prefix, stem in stems.items():
            if token.startswith(prefix):
                return stem
        return token

    @classmethod
    def _score_payload(cls, query_tokens: set, payload: Dict[str, Any], vector_score: float) -> float:
        if not query_tokens:
            return min(1.0, vector_score)

        payload_text = " ".join(
            str(payload.get(key, ""))
            for key in ["filename", "document_type", "academic_year", "text"]
        )
        payload_tokens = cls._tokens(payload_text)
        overlap = query_tokens.intersection(payload_tokens)
        lexical_score = len(overlap) / len(query_tokens)

        if not overlap:
            return min(0.15, vector_score * 0.15)

        return min(1.0, lexical_score * 0.85 + vector_score * 0.15)


class QdrantVectorStore:
    """
    Qdrant Vector Database Integration wrapper for RAG operations.
    """

    def __init__(self, collection_name: Optional[str] = None):
        self.collection_name = collection_name or settings.QDRANT_COLLECTION
        self.qdrant_url = settings.effective_qdrant_url
        self.mock_fallback = MockQdrantVectorStore(self.collection_name)
        self.client = None
        self._connection_error: Optional[Exception] = None
        self._connect()

    def _connect(self):
        try:
            from qdrant_client import QdrantClient
            self.client = QdrantClient(
                url=self.qdrant_url,
                api_key=settings.QDRANT_API_KEY or None,
                timeout=0.25 if settings.mocks_allowed else settings.EXTERNAL_REQUEST_TIMEOUT_SECONDS,
                check_compatibility=False,
            )
            logger.info(f"Initialized Qdrant client for {self.qdrant_url}")
        except Exception as e:
            self._connection_error = e
            if settings.mocks_allowed:
                logger.warning(
                    "Could not initialize Qdrant client (%s). Using development mock vector store.",
                    type(e).__name__,
                )
            else:
                logger.error("Could not initialize Qdrant client (%s).", type(e).__name__)
            self.client = None

    async def _use_mock_or_raise(self) -> bool:
        if self.client:
            return False
        if settings.mocks_allowed:
            return True
        raise RAGRetrievalException("Qdrant is unavailable")

    async def _fallback_or_raise(self, operation: str, exc: Exception):
        self._connection_error = exc
        self.client = None
        if settings.mocks_allowed:
            logger.warning("Qdrant %s failed (%s); using development mock vector store.", operation, type(exc).__name__)
            return self.mock_fallback
        raise RAGRetrievalException(f"Qdrant {operation} failed") from exc

    async def init_collection(self, vector_size: int = 1536):
        if await self._use_mock_or_raise():
            return await self.mock_fallback.init_collection(vector_size)

        try:
            from qdrant_client.http import models
            collections = (await asyncio.to_thread(self.client.get_collections)).collections
            exists = any(c.name == self.collection_name for c in collections)

            if not exists:
                await asyncio.to_thread(
                    self.client.create_collection,
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
                )
                logger.info(f"Created Qdrant collection '{self.collection_name}'.")
            else:
                collection = await asyncio.to_thread(self.client.get_collection, self.collection_name)
                vectors = collection.config.params.vectors
                configured_size = getattr(vectors, "size", None)
                if configured_size is not None and configured_size != vector_size:
                    raise RAGRetrievalException(
                        f"Qdrant collection '{self.collection_name}' has vector size {configured_size}, "
                        f"but EMBEDDING_VECTOR_SIZE is {vector_size}. Use a collection with matching embeddings."
                    )
        except Exception as e:
            fallback = await self._fallback_or_raise("collection initialization", e)
            await fallback.init_collection(vector_size)

    async def upsert_chunks(self, chunks: List[RAGChunkSchema], vectors: List[List[float]]) -> int:
        if await self._use_mock_or_raise():
            return await self.mock_fallback.upsert_chunks(chunks, vectors)

        try:
            if len(chunks) != len(vectors):
                raise RAGRetrievalException(
                    f"Embedding count {len(vectors)} does not match chunk count {len(chunks)}"
                )
            wrong_dimensions = [index for index, vector in enumerate(vectors) if len(vector) != settings.EMBEDDING_VECTOR_SIZE]
            if wrong_dimensions:
                raise RAGRetrievalException(
                    f"Embedding dimension mismatch at chunk {wrong_dimensions[0]}: expected "
                    f"{settings.EMBEDDING_VECTOR_SIZE}, got {len(vectors[wrong_dimensions[0]])}"
                )
            from qdrant_client.http import models
            points = []
            for chunk, vector in zip(chunks, vectors):
                point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk.chunk_id))
                payload = {
                    "chunk_id": chunk.chunk_id,
                    "document_id": chunk.document_id,
                    "filename": chunk.filename,
                    "academic_year": chunk.academic_year,
                    "page": chunk.page,
                    "chunk_index": chunk.chunk_index,
                    "source_path": chunk.source_path,
                    "text": chunk.text,
                    "checksum": chunk.checksum,
                    "document_type": chunk.document_type
                }
                points.append(models.PointStruct(id=point_id, vector=vector, payload=payload))

            await asyncio.to_thread(self.client.upsert, collection_name=self.collection_name, points=points, wait=True)
            logger.info(f"Successfully upserted {len(points)} points to Qdrant collection '{self.collection_name}'.")
            return len(points)
        except Exception as e:
            fallback = await self._fallback_or_raise("upsert", e)
            return await fallback.upsert_chunks(chunks, vectors)

    async def search_similarity(
        self,
        query_vector: List[float],
        academic_year: Optional[str] = None,
        top_k: int = 5,
        score_threshold: float = 0.35,
        query_text: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        if await self._use_mock_or_raise():
            return await self.mock_fallback.search_similarity(query_vector, academic_year, top_k, score_threshold, query_text)

        try:
            from qdrant_client.http import models
            query_filter = None

            if academic_year:
                if academic_year == "general":
                    query_filter = models.Filter(
                        must=[
                            models.FieldCondition(
                                key="academic_year",
                                match=models.MatchValue(value="general")
                            )
                        ]
                    )
                else:
                    query_filter = models.Filter(
                        should=[
                            models.FieldCondition(
                                key="academic_year",
                                match=models.MatchValue(value=academic_year)
                            ),
                            models.FieldCondition(
                                key="academic_year",
                                match=models.MatchValue(value="general")
                            ),
                        ]
                    )

            response = await asyncio.to_thread(
                self.client.query_points,
                collection_name=self.collection_name,
                query=query_vector,
                query_filter=query_filter,
                limit=top_k,
                score_threshold=score_threshold,
            )

            hits = []
            for point in response.points:
                hits.append({
                    "score": point.score,
                    "payload": point.payload or {}
                })
            return hits
        except Exception as e:
            fallback = await self._fallback_or_raise("similarity search", e)
            return await fallback.search_similarity(query_vector, academic_year, top_k, score_threshold, query_text)

    async def delete_document_vectors(
        self,
        document_id: Optional[str] = None,
        academic_year: Optional[str] = None,
        source_path: Optional[str] = None,
        checksum: Optional[str] = None,
    ) -> int:
        if await self._use_mock_or_raise():
            return await self.mock_fallback.delete_document_vectors(document_id, academic_year, source_path, checksum)

        try:
            from qdrant_client.http import models

            conditions = []
            if document_id:
                conditions.append(models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id)))
            if academic_year:
                conditions.append(models.FieldCondition(key="academic_year", match=models.MatchValue(value=academic_year)))
            if source_path:
                conditions.append(models.FieldCondition(key="source_path", match=models.MatchValue(value=source_path)))
            if checksum:
                conditions.append(models.FieldCondition(key="checksum", match=models.MatchValue(value=checksum)))

            if not conditions:
                return 0

            await asyncio.to_thread(
                self.client.delete,
                collection_name=self.collection_name,
                points_selector=models.FilterSelector(filter=models.Filter(must=conditions)),
                wait=True,
            )
            logger.info(f"Deleted old vectors from Qdrant collection '{self.collection_name}'.")
            return 0
        except Exception as e:
            fallback = await self._fallback_or_raise("vector deletion", e)
            return await fallback.delete_document_vectors(document_id, academic_year, source_path, checksum)
