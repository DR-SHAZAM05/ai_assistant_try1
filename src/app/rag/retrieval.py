from typing import List, Dict, Any, Optional
from src.app.rag.embeddings import get_embedding_provider, EmbeddingProvider
from src.app.rag.vector_store import QdrantVectorStore
from src.app.core.config import settings
from src.app.core.logging import logger
from src.app.core.exceptions import RAGRetrievalException


class RAGRetriever:
    """
    RAG Semantic Search & Context Retriever.
    Queries Qdrant vector store with academic_year metadata filtering and score thresholding.
    """

    def __init__(
        self,
        vector_store: Optional[QdrantVectorStore] = None,
        embedding_provider: Optional[EmbeddingProvider] = None
    ):
        self.embedding_provider = embedding_provider or get_embedding_provider()
        self.vector_store = vector_store or QdrantVectorStore()

    async def retrieve_context(
        self,
        user_query: str,
        academic_year: Optional[str] = None,
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Generates query embedding vector, performs filtered search in Qdrant,
        and returns relevant chunks and metadata.
        """
        target_year = academic_year or settings.CURRENT_ACADEMIC_YEAR
        result_limit = top_k if top_k is not None else settings.RAG_TOP_K
        min_score = score_threshold if score_threshold is not None else settings.RAG_SCORE_THRESHOLD
        logger.info(
            "RAGRetriever searching context (query_length=%s, academic_year=%s).",
            len(user_query),
            target_year,
        )

        try:
            # 1. Embed query text
            query_vector = await self.embedding_provider.embed_text(user_query)
            if len(query_vector) != settings.EMBEDDING_VECTOR_SIZE:
                raise RAGRetrievalException(
                    f"Embedding size mismatch: configured {settings.EMBEDDING_VECTOR_SIZE}, got {len(query_vector)}"
                )

            # 2. Query Qdrant with academic_year filter
            hits = await self.vector_store.search_similarity(
                query_vector=query_vector,
                academic_year=target_year,
                top_k=result_limit,
                score_threshold=min_score,
                query_text=user_query,
            )
        except Exception as exc:
            if isinstance(exc, RAGRetrievalException):
                raise
            logger.error("RAG retrieval failed (%s).", type(exc).__name__)
            raise RAGRetrievalException("RAG retrieval failed") from exc

        logger.info(f"Retrieved {len(hits)} relevant context chunks from Qdrant.")
        return hits
