import re
import unicodedata
from typing import Dict, Any, Optional, List
from src.app.rag.retrieval import RAGRetriever
from src.app.rag.ingestion import IngestionPipeline
from src.app.rag.vector_store import QdrantVectorStore
from src.app.llm.factory import get_llm_provider
from src.app.services.practice_history_service import PracticeHistoryService
from src.app.core.config import settings
from src.app.core.logging import logger
from src.app.core.exceptions import LLMProviderException, RAGRetrievalException


class PracticeAgent:
    """
    Specialized Practice Agent integrating RAG Engine, Qdrant Vector Search,
    strict Anti-Hallucination Guardrails, and Source Attribution.
    """

    def __init__(
        self,
        retriever: Optional[RAGRetriever] = None,
        llm_provider=None,
        practice_history_service: Optional[PracticeHistoryService] = None,
    ):
        self.vector_store = retriever.vector_store if retriever else QdrantVectorStore()
        self.retriever = retriever or RAGRetriever(vector_store=self.vector_store)
        self.llm = llm_provider or get_llm_provider()
        self.ingestion_pipeline = IngestionPipeline(vector_store=self.vector_store)
        self.practice_history_service = practice_history_service or PracticeHistoryService()
        self._is_ingested = False

    def detect_academic_year(self, user_prompt: str) -> str:
        """
        Parses explicit academic year from prompt (e.g. '2025-2026') or returns default current year.
        """
        match = re.search(r"20\d{2}-20\d{2}", user_prompt)
        if match:
            return match.group(0)
        return settings.CURRENT_ACADEMIC_YEAR

    def detect_historical_academic_year(self, user_prompt: str) -> str:
        explicit_year = re.search(r"20\d{2}-20\d{2}", user_prompt)
        if explicit_year:
            return explicit_year.group(0)

        prompt_lower = user_prompt.lower()
        if any(marker in prompt_lower for marker in ["anul trecut", "anul anterior", "year before", "last year"]):
            current_start, current_end = settings.CURRENT_ACADEMIC_YEAR.split("-")
            return f"{int(current_start) - 1}-{int(current_end) - 1}"

        return settings.CURRENT_ACADEMIC_YEAR

    async def _ensure_ingested(self):
        """Auto-ingest sample knowledge base if not already indexed."""
        if not self._is_ingested:
            await self.ingestion_pipeline.ingest_all()
            self._is_ingested = True

    async def handle_practice_query(
        self,
        user_prompt: str,
        academic_year: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Main execution flow:
        User Question -> Determine Academic Year -> RAG Retriever Search ->
        Anti-Hallucination Check -> LLM Synthesis -> Response + Citations
        """
        target_year = academic_year or self.detect_academic_year(user_prompt)
        logger.info(
            "PracticeAgent processing query (query_length=%s, academic_year=%s).",
            len(user_prompt),
            target_year,
        )

        # Auto-ingest documents if needed
        try:
            await self._ensure_ingested()
        except Exception as exc:
            logger.error("Practice KB ingestion failed before query (%s).", type(exc).__name__)
            return {
                "text": "Nu am putut accesa baza de cunoștințe de practică momentan. Încearcă din nou mai târziu.",
                "sources": [],
                "chunks_count": 0,
                "academic_year": target_year
            }

        # 1. RAG Search
        try:
            chunks = await self.retriever.retrieve_context(
                user_query=user_prompt,
                academic_year=target_year,
                top_k=settings.RAG_TOP_K,
                score_threshold=settings.RAG_SCORE_THRESHOLD
            )
        except RAGRetrievalException as exc:
            logger.error("Practice RAG retrieval unavailable (%s).", type(exc).__name__)
            return {
                "text": "Nu am putut accesa baza de cunoștințe de practică momentan. Încearcă din nou mai târziu.",
                "sources": [],
                "chunks_count": 0,
                "academic_year": target_year
            }

        # 2. Strict Anti-Hallucination Check
        if not chunks:
            logger.info("No relevant practice chunks found (academic_year=%s).", target_year)
            return {
                "text": f"Nu am găsit informații suficiente sau informația necesară în documentele disponibile pentru anul universitar {target_year}.",
                "sources": [],
                "chunks_count": 0,
                "academic_year": target_year
            }

        # 3. Build Context Text and Source Citations
        context_lines = []
        sources_list = []
        seen_citations = set()

        for c in chunks:
            payload = c.get("payload", {})
            text_snippet = payload.get("text", "")
            filename = payload.get("filename", "Document_Practică")
            page = payload.get("page", 1)
            
            context_lines.append(f"--- Document: {filename} (Pagina {page}) ---\n{text_snippet}\n")
            
            citation_str = f"{filename} (pagina {page})"
            if citation_str not in seen_citations:
                seen_citations.add(citation_str)
                sources_list.append({"filename": filename, "page": page, "academic_year": target_year})

        full_context = "\n".join(context_lines)

        temporal_evidence = self._find_temporal_evidence(user_prompt, chunks)

        # 4. Synthesize Answer using LLM
        prompt = (
            f"Întrebare student: '{user_prompt}'\n\n"
            f"Context extras din Knowledge Base (An Universitar {target_year}):\n"
            f"{full_context}\n\n"
            f"Instrucțiuni:\n"
            f"1. Răspunde amabil, clar și structurat în limba română doar pe baza CONTEXTULUI de mai sus.\n"
            f"2. Nu adăuga speculații, proceduri sau date care nu apar în textul oferit.\n"
            f"3. Pentru întrebări despre termene, date, intervale sau durate, oferă mai întâi valoarea temporală exactă din context. "
            f"Nu înlocui termenul cerut cu o listă de documente sau cu o procedură asociată.\n"
            f"4. Dacă textul oferit nu conține informația necesară, spune explicit că informația nu este disponibilă în documentele furnizate.\n"
        )

        system_prompt = (
            "Ești asistentul oficial de practică al Universității Transilvania din Brașov (UNITBV). "
            "Answer only using the provided context. Do not invent information. "
            "If the context does not contain enough information, explicitly state that the information is not available in the provided documents."
        )

        try:
            llm_res = await self.llm.generate_completion(
                prompt=prompt,
                system_prompt=system_prompt,
                history=history,
                temperature=0.0,
            )
            answer = llm_res.get("content", "").strip()
        except (LLMProviderException, Exception) as exc:
            logger.error("Practice LLM synthesis failed (%s).", type(exc).__name__)
            answer = self._build_extractive_answer(chunks, target_year)

        if not answer or answer.startswith("[Simulated Cloud LLM Response]") or answer.startswith("[Simulated LLM Fallback]"):
            answer = self._build_extractive_answer(chunks, target_year)
        elif temporal_evidence and not self._contains_all_evidence_values(answer, temporal_evidence["values"]):
            logger.warning(
                "Practice LLM answer omitted temporal evidence; using source-backed extractive response."
            )
            answer = (
                f"Conform documentelor de practică disponibile pentru anul universitar {target_year}:\n"
                f"- {temporal_evidence['text']}"
            )

        # 5. Append Citation Footnotes
        sources_formatted = ", ".join([f"`{s['filename']}` (pagina {s['page']})" for s in sources_list])
        response_text = f"{answer}\n\n📚 **Surse**: {sources_formatted} [{target_year}]"

        return {
            "text": response_text,
            "raw_answer": answer,
            "sources": sources_list,
            "chunks_count": len(chunks),
            "academic_year": target_year
        }

    async def handle_historical_practice_query(
        self,
        user_prompt: str,
        academic_year: Optional[str] = None
    ) -> Dict[str, Any]:
        target_year = academic_year or self.detect_historical_academic_year(user_prompt)
        history = await self.practice_history_service.find_similar(
            query=user_prompt,
            academic_year=target_year,
            limit=3,
        )

        if not history:
            return {
                "text": f"Nu am găsit răspunsuri istorice despre practică pentru anul universitar {target_year}.",
                "sources": [],
                "history_count": 0,
                "academic_year": target_year,
            }

        lines = [f"Am găsit răspunsuri istorice despre practică pentru anul universitar {target_year}:\n"]
        sources = []
        for idx, item in enumerate(history, 1):
            lines.append(f"{idx}. Tema: {item.topic}")
            lines.append(f"   Întrebare: {item.question_summary}")
            lines.append(f"   Răspuns: {item.answer_summary}")
            lines.append(f"   Sursă: {item.source_type} ({item.source_reference or 'fără referință'})")
            lines.append("")
            sources.append({
                "source_type": item.source_type,
                "source_reference": item.source_reference,
                "academic_year": item.academic_year,
                "topic": item.topic,
            })

        return {
            "text": "\n".join(lines).strip(),
            "sources": sources,
            "history_count": len(history),
            "academic_year": target_year,
        }

    @staticmethod
    def _build_extractive_answer(chunks: List[Dict[str, Any]], academic_year: str) -> str:
        snippets = []
        for chunk in chunks[:3]:
            text = chunk.get("payload", {}).get("text", "").strip()
            if not text:
                continue
            first_part = re.split(r"(?<=[.!?])\s+", text, maxsplit=2)
            snippets.append(" ".join(first_part[:2]).strip())

        if not snippets:
            return f"Am găsit surse pentru anul universitar {academic_year}, dar nu pot extrage un răspuns sigur din ele momentan."

        bullets = "\n".join(f"- {snippet}" for snippet in snippets)
        return f"Conform documentelor de practică disponibile pentru anul universitar {academic_year}:\n{bullets}"

    @classmethod
    def _find_temporal_evidence(
        cls,
        user_prompt: str,
        chunks: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Find the most relevant dated source line for deadline-style questions."""
        normalized_query = cls._normalize_for_match(user_prompt)
        temporal_markers = {"cand", "termen", "deadline", "data", "perioada", "interval", "durata", "ore", "saptamani"}
        raw_query_tokens = set(re.findall(r"[a-z0-9]+", normalized_query))
        if not any(
            token == marker or token.startswith(marker)
            for token in raw_query_tokens
            for marker in temporal_markers
        ):
            return None
        query_tokens = cls._content_tokens(normalized_query)
        asks_for_date = any(
            token == marker or token.startswith(marker)
            for token in raw_query_tokens
            for marker in {"cand", "termen", "deadline", "data", "perioada", "interval"}
        )

        month_names = (
            "ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|"
            "septembrie|octombrie|noiembrie|decembrie"
        )
        date_pattern = re.compile(
            rf"\b\d{{1,2}}\s*(?:-|–|pana la)?\s*\d{{0,2}}\s*(?:{month_names})\s+\d{{4}}\b"
        )
        duration_pattern = re.compile(r"\b\d+\s+(?:de\s+)?(?:ore|saptamani|zile)\b")
        candidates = []

        for chunk in chunks:
            text = str(chunk.get("payload", {}).get("text", ""))
            for line in re.split(r"\n+|(?<=[.!?])\s+", text):
                candidate = line.strip().lstrip("- ").strip()
                normalized_candidate = cls._normalize_for_match(candidate)
                date_values = date_pattern.findall(normalized_candidate)
                duration_values = duration_pattern.findall(normalized_candidate)
                values = date_values + duration_values
                if not values:
                    continue
                candidate_tokens = cls._content_tokens(normalized_candidate)
                overlap = len(query_tokens.intersection(candidate_tokens))
                candidates.append((overlap, bool(date_values), len(values), candidate, values))

        if not candidates:
            return None

        if asks_for_date:
            dated_candidates = [candidate for candidate in candidates if candidate[1]]
            if dated_candidates:
                candidates = dated_candidates

        _, _, _, text, values = max(
            candidates,
            key=lambda candidate: (candidate[0], candidate[1], candidate[2], len(candidate[3])),
        )
        return {"text": text, "values": values}

    @staticmethod
    def _normalize_for_match(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text.casefold())
        return "".join(character for character in normalized if not unicodedata.combining(character))

    @staticmethod
    def _content_tokens(text: str) -> set[str]:
        stopwords = {
            "a", "ai", "al", "ale", "anul", "care", "ce", "cu", "de", "din", "este",
            "in", "la", "o", "pe", "pentru", "sau", "si", "se", "sunt", "un", "unei",
            "universitar",
        }
        stems = {
            "adever": "adeverinta",
            "caiet": "caiet",
            "colocv": "colocviu",
            "convent": "conventie",
            "document": "document",
            "incarc": "incarcare",
            "practic": "practica",
            "termen": "termen",
        }
        result = set()
        for token in re.findall(r"[a-z0-9]+", text):
            if token.isdigit() or len(token) < 3 or token in stopwords:
                continue
            for prefix, stem in stems.items():
                if token.startswith(prefix):
                    token = stem
                    break
            result.add(token)
        return result

    @classmethod
    def _contains_all_evidence_values(cls, answer: str, values: List[str]) -> bool:
        normalized_answer = cls._normalize_for_match(answer)
        return all(cls._normalize_for_match(value) in normalized_answer for value in values)
