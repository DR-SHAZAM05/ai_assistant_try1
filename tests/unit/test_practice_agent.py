import pytest
from types import SimpleNamespace
from src.app.agents.practice_agent import PracticeAgent
from src.app.core.exceptions import RAGRetrievalException
from src.app.rag.vector_store import MockQdrantVectorStore


def test_academic_year_detection():
    agent = PracticeAgent()
    assert agent.detect_academic_year("Care sunt regulile pentru 2025-2026?") == "2025-2026"
    assert agent.detect_academic_year("Cum se face practica?") == "2026-2027"


@pytest.mark.asyncio
async def test_practice_agent_query():
    agent = PracticeAgent()
    res = await agent.handle_practice_query("Care sunt pașii pentru efectuarea practicii?")
    assert "text" in res
    assert "sources" in res
    assert res["academic_year"] == "2026-2027"


@pytest.mark.asyncio
async def test_practice_agent_anti_hallucination():
    agent = PracticeAgent()
    # Query non-existent procedure
    res = await agent.handle_practice_query("Care este procedura secretă XZY123?")
    assert "Nu am găsit informații" in res["text"] or "Surse" in res["text"]


class FailingRetriever:
    def __init__(self):
        self.vector_store = MockQdrantVectorStore("test_failing_retriever")

    async def retrieve_context(self, *args, **kwargs):
        raise RAGRetrievalException("qdrant unavailable")


class StaticRetriever:
    def __init__(self):
        self.vector_store = MockQdrantVectorStore("test_static_retriever")

    async def retrieve_context(self, *args, **kwargs):
        return [
            {
                "score": 0.9,
                "payload": {
                    "text": "Pentru practica UNITBV sunt necesare conventia, caietul si adeverinta.",
                    "filename": "Ghid_Practica_2026_2027.md",
                    "page": 1,
                    "academic_year": "2026-2027",
                },
            }
        ]


class TemporalRetriever:
    def __init__(self):
        self.vector_store = MockQdrantVectorStore("test_temporal_retriever")

    async def retrieve_context(self, *args, **kwargs):
        return [
            {
                "score": 0.95,
                "payload": {
                    "text": (
                        "Depunere conventie de practica: Pana la data de 28 august 2026.\n"
                        "Incarcare caiet de practica si adeverinta: Pana la data de 2 septembrie 2026."
                    ),
                    "filename": "Ghid_Practica_2026_2027.md",
                    "page": 1,
                    "academic_year": "2026-2027",
                },
            }
        ]


class FailingLLM:
    async def generate_completion(self, *args, **kwargs):
        raise RuntimeError("llm timeout")


class CapturingLLM:
    def __init__(self):
        self.kwargs = None

    async def generate_completion(self, *args, **kwargs):
        self.kwargs = kwargs
        return {"content": "Termenul este 2 septembrie 2026."}


class FakePracticeHistory:
    async def find_similar(self, **kwargs):
        return [
            SimpleNamespace(
                academic_year=kwargs.get("academic_year"),
                topic="erasmus",
                question_summary="Studentul întreabă despre practica Erasmus.",
                answer_summary="Pentru Erasmus se folosește Learning Agreement for Traineeship.",
                source_type="unitbv_email",
                source_reference="msg-old-1",
            )
        ]


@pytest.mark.asyncio
async def test_practice_agent_handles_qdrant_failure_gracefully():
    agent = PracticeAgent(retriever=FailingRetriever())
    agent._is_ingested = True

    res = await agent.handle_practice_query("Ce documente sunt necesare pentru practica?")

    assert "Nu am putut accesa baza de cunoștințe" in res["text"]
    assert res["sources"] == []


@pytest.mark.asyncio
async def test_practice_agent_handles_llm_failure_with_sources():
    agent = PracticeAgent(retriever=StaticRetriever(), llm_provider=FailingLLM())
    agent._is_ingested = True

    res = await agent.handle_practice_query("Ce documente sunt necesare pentru practica?")

    assert "Conform documentelor de practică" in res["text"]
    assert "Surse" in res["text"]
    assert res["sources"][0]["filename"] == "Ghid_Practica_2026_2027.md"


@pytest.mark.asyncio
async def test_practice_agent_uses_deterministic_grounded_generation():
    llm = CapturingLLM()
    agent = PracticeAgent(retriever=StaticRetriever(), llm_provider=llm)
    agent._is_ingested = True

    await agent.handle_practice_query("Care este termenul pentru practica?")

    assert llm.kwargs["temperature"] == 0.0
    assert "valoarea temporală exactă" in llm.kwargs["prompt"]


@pytest.mark.asyncio
async def test_practice_agent_replaces_wrong_deadline_with_source_evidence():
    class WrongDeadlineLLM:
        async def generate_completion(self, *args, **kwargs):
            return {"content": "Termenul este 28 august 2026."}

    agent = PracticeAgent(retriever=TemporalRetriever(), llm_provider=WrongDeadlineLLM())
    agent._is_ingested = True

    response = await agent.handle_practice_query("Care este termenul pentru incarcarea caietului de practica si adeverintei?")

    assert "2 septembrie 2026" in response["raw_answer"]
    assert "28 august 2026" not in response["raw_answer"]


@pytest.mark.asyncio
async def test_temporal_evidence_prefers_the_requested_deadline_over_duration():
    chunks = await TemporalRetriever().retrieve_context()
    chunks[0]["payload"]["text"] = (
        "Practica are o durata de 90 de ore.\n"
        "Depunere conventie de practica: Pana la data de 28 august 2026.\n"
        "Incarcare caiet de practica si adeverinta: Pana la data de 2 septembrie 2026."
    )

    evidence = PracticeAgent._find_temporal_evidence(
        "Care este termenul pentru incarcarea caietului de practica si adeverintei?",
        chunks,
    )

    assert evidence is not None
    assert evidence["values"] == ["2 septembrie 2026"]


def test_historical_academic_year_detection():
    agent = PracticeAgent()
    assert agent.detect_historical_academic_year("Ce am răspuns anul trecut despre Erasmus?") == "2025-2026"
    assert agent.detect_historical_academic_year("Ce am răspuns în 2024-2025?") == "2024-2025"


@pytest.mark.asyncio
async def test_practice_agent_historical_query_returns_saved_answers():
    agent = PracticeAgent(practice_history_service=FakePracticeHistory())

    res = await agent.handle_historical_practice_query("Ce am răspuns anul trecut despre Erasmus?")

    assert res["academic_year"] == "2025-2026"
    assert res["history_count"] == 1
    assert "Learning Agreement" in res["text"]
    assert res["sources"][0]["source_reference"] == "msg-old-1"
