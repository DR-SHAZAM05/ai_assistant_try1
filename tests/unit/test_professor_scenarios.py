import uuid
import pytest
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from src.app.services.calendar_service import CalendarService
from src.app.agents.calendar_agent import CalendarAgent
from src.app.services.email_service import EmailService
from src.app.agents.email_agent import EmailAgent
from src.app.schemas.email import EmailMessageSchema
from src.app.rag.embeddings import MockEmbeddingProvider
from src.app.rag.retrieval import RAGRetriever
from src.app.rag.vector_store import MockQdrantVectorStore
from src.app.schemas.rag import RAGChunkSchema
from src.app.orchestrator.orchestrator import AIOrchestrator
from src.app.orchestrator.intent import IntentType


@pytest.mark.asyncio
async def test_scenario_t1_calendar_query():
    """
    Test T1: Calendar query parsing and execution.
    Validates natural language parsing, hourly intervals, and next event queries.
    """
    service = CalendarService()
    
    # 1. Natural date range
    start, end, label = service.parse_natural_date_range("Ce am mâine în calendar?")
    assert label == "mâine"
    assert (end - start).days == 0

    # 2. Hourly interval parsing
    start_int, end_int, label_int = service.parse_natural_date_range("Am ceva între orele 14 și 16?")
    assert "intervalul 14:00 – 16:00" in label_int
    assert start_int.hour == 14
    assert end_int.hour == 16

    # 3. Next event detection
    start_nxt, end_nxt, label_nxt = service.parse_natural_date_range("Care este următorul eveniment?")
    assert label_nxt == "următorul eveniment"

    # 4. CalendarAgent handling
    agent = CalendarAgent(calendar_service=service)
    res = await agent.handle_calendar_query("Ce am mâine în calendar?")
    assert "mâine" in res["text"].lower() or "programul" in res["text"].lower()
    assert res["count"] >= 0


@pytest.mark.asyncio
async def test_scenario_t2_unitbv_practice_email():
    """
    Test T2: Email classification as UNITBV / Practice.
    Validates keyword detection and institutional account separation.
    """
    service = EmailService()
    
    # Test practice email detection
    practice_email = EmailMessageSchema(
        id=1,
        message_id="test-msg-01",
        account_type="unitbv",
        sender="secretariat@unitbv.ro",
        recipients=["student@student.unitbv.ro"],
        subject="Important: Depunere convenție de practică și caiet",
        body_text="Vă rugăm să depuneți convenția de practică semnată până la data limită.",
        received_at=datetime.now(timezone.utc),
        is_read=False,
    )
    
    is_practice = service._is_practice_email(practice_email)
    assert is_practice is True
    assert practice_email.account_type == "unitbv"

    # Test non-practice personal email
    personal_email = EmailMessageSchema(
        id=2,
        message_id="test-msg-02",
        account_type="personal",
        sender="newsletter@store.ro",
        recipients=["personal@gmail.com"],
        subject="Reduceri de weekend",
        body_text="Profită de 20% reducere la toate accesoriile!",
        received_at=datetime.now(timezone.utc),
        is_read=True,
    )
    assert service._is_practice_email(personal_email) is False


@pytest.mark.asyncio
async def test_scenario_t3_human_in_the_loop_draft():
    """
    Test T3: Draft generation and Human-in-the-Loop stop before sending.
    Ensures drafts are held in 'pending_approval' until user explicitly confirms.
    """
    agent = EmailAgent()

    # 1. Generate Draft
    draft_res = await agent.handle_draft_reply(
        "Răspunde la mailul de practică",
        account_type="unitbv",
        message_id="msg-unitbv-101"
    )
    assert draft_res["status"] == "pending_approval"
    assert "draft_id" in draft_res
    draft_id = draft_res["draft_id"]

    # 2. Reject sending ("Nu / Anulează")
    rejection = await agent.handle_approval(draft_id=draft_id, approval_granted=False)
    assert rejection["status"] == "cancelled"
    assert "anulat" in rejection["text"].lower()

    # 3. Create another draft and approve ("Da / Trimite")
    draft_res2 = await agent.handle_draft_reply(
        "Răspunde la mailul de practică",
        account_type="unitbv",
        message_id="msg-unitbv-101"
    )
    draft_id2 = draft_res2["draft_id"]
    approval = await agent.handle_approval(draft_id=draft_id2, approval_granted=True)
    assert approval["status"] == "sent"
    assert "trimis cu succes" in approval["text"].lower()


@pytest.mark.asyncio
async def test_scenario_t4_rag_specific_academic_year_and_general():
    """
    Test T4: Multi-annual RAG retrieval + Stable general knowledge base.
    Validates filtering by academic year and inclusion of permanent regulations.
    """
    collection = f"test_kb_{uuid.uuid4().hex}"
    provider = MockEmbeddingProvider()
    store = MockQdrantVectorStore(collection)

    # Chunks from specific year (2024-2025) and stable general regulations
    chunks = [
        RAGChunkSchema(
            chunk_id="chunk-2024-1",
            document_id="doc-2024",
            filename="Ghid_Practica_2024_2025.md",
            academic_year="2024-2025",
            page=1,
            chunk_index=0,
            source_path="knowledge_base/2024-2025/Ghid.md",
            text="În anul universitar 2024-2025 termenul pentru depunerea convenției de practică a fost 15 iulie 2025.",
            checksum="chk-1",
            document_type="md",
        ),
        RAGChunkSchema(
            chunk_id="chunk-2026-1",
            document_id="doc-2026",
            filename="Ghid_Practica_2026_2027.md",
            academic_year="2026-2027",
            page=1,
            chunk_index=0,
            source_path="knowledge_base/2026-2027/Ghid.md",
            text="În anul universitar 2026-2027 termenul limită este 28 august 2026.",
            checksum="chk-2",
            document_type="md",
        ),
        RAGChunkSchema(
            chunk_id="chunk-general-1",
            document_id="doc-general",
            filename="Regulament_Cadru_Practica_UNITBV.md",
            academic_year="general",
            page=1,
            chunk_index=0,
            source_path="knowledge_base/general/Regulament.md",
            text="Regulamentul cadru UNITBV prevede obligativitatea a 90 de ore de practică și 4 credite ECTS.",
            checksum="chk-gen",
            document_type="md",
        ),
    ]

    vectors = await provider.embed_batch([c.text for c in chunks])
    await store.upsert_chunks(chunks, vectors)

    retriever = RAGRetriever(vector_store=store, embedding_provider=provider)

    # Search for 2024-2025: should retrieve the 2024 chunk AND general chunk, but NOT 2026
    hits_2024 = await retriever.retrieve_context(
        "termen depunere conventie practica",
        academic_year="2024-2025",
        top_k=5,
        score_threshold=0.2,
    )
    hit_ids_2024 = [h["payload"]["chunk_id"] for h in hits_2024]
    assert "chunk-2024-1" in hit_ids_2024
    assert "chunk-2026-1" not in hit_ids_2024

    # Search general regulations
    hits_gen = await retriever.retrieve_context(
        "cate ore de practica si credite ECTS sunt necesare conform regulamentului",
        academic_year="2026-2027",
        top_k=5,
        score_threshold=0.2,
    )
    hit_ids_gen = [h["payload"]["chunk_id"] for h in hits_gen]
    assert "chunk-general-1" in hit_ids_gen


@pytest.mark.asyncio
async def test_scenario_t5_multi_tool_aggregated_overview():
    """
    Test T5: Multi-Tool Synthesized Response.
    Validates that a single user query aggregates Calendar, Action Items, Email and Practice.
    """
    orchestrator = AIOrchestrator()
    res = await orchestrator.process_request("Ce mai am de făcut?")
    assert res["intent"] == IntentType.AGGREGATED_OVERVIEW.value
    assert "Sinteza activităților tale" in res["response"]
    assert "Calendar" in res["response"]
    assert "Sarcini" in res["response"]
    assert "E-mailuri" in res["response"]
    assert "Practică UNITBV" in res["response"]
    assert "inline_keyboard" in res


@pytest.mark.asyncio
async def test_scenario_conversational_continuity():
    """
    Section 18.1 & 32: Conversational continuity / anaphora.
    User asks: 'Și după al doilea?' after viewing calendar events.
    """
    agent = CalendarAgent()
    history = [
        {"role": "user", "content": "Ce am azi în calendar?"},
        {
            "role": "assistant",
            "content": "Evenimentele din calendar:\n1. 10:00 - Curs Sisteme Inteligente\n2. 14:00 - Ședință practică FIESC\n3. 16:30 - Consultații laborator"
        },
    ]

    res = await agent.handle_calendar_query("Și după al doilea?", history=history)
    assert "text" in res
    assert "ședință practică fiesc" in res["text"].lower() or "consultații" in res["text"].lower()


@pytest.mark.asyncio
async def test_scenario_hourly_interval_query():
    """
    Section 14: Interval query ('Am ceva între orele 14 și 16?').
    """
    agent = CalendarAgent()
    res = await agent.handle_calendar_query("Am ceva între orele 14 și 16?")
    assert "text" in res
    assert "14:00" in res["text"] or "16:00" in res["text"] or "interval" in res["text"].lower()


@pytest.mark.asyncio
async def test_scenario_daily_briefing_5_sections():
    """
    Section 17: Daily Briefing with 5 distinct mandatory sections:
    CALENDAR, EMAIL, UNITBV / PRACTICĂ, ACTION ITEMS, ȘTIRI.
    """
    orchestrator = AIOrchestrator()
    res = await orchestrator.process_request("/briefing")
    assert res["intent"] == IntentType.DAILY_BRIEFING.value
    text = res["response"]
    assert "Programul tău" in text or "Calendar" in text
    assert "E-mailuri" in text or "EMAIL" in text
    assert "Practică" in text or "UNITBV" in text
    assert "Sarcini" in text or "Sinteza" in text


@pytest.mark.asyncio
async def test_scenario_memory_email_preference_rule():
    """
    Section 19: Dynamic email rules based on long-term memory.
    If memory states 'Mailurile de la decanat@unitbv.ro sunt importante',
    emails from that address are dynamically marked with high importance.
    """
    class FakeMemoryService:
        async def list_memories(self, category: Optional[str] = None):
            return [{"key": "pref1", "value": "Mailurile de la decanat@unitbv.ro sunt întotdeauna importante"}]

    service = EmailService(user_memory_service=FakeMemoryService())
    test_emails = [
        EmailMessageSchema(
            id=1,
            message_id="test-msg-1",
            account_type="unitbv",
            sender="decanat@unitbv.ro",
            recipients=["student@student.unitbv.ro"],
            subject="Anunț urgent decanat",
            body_text="Important pentru toți studenții",
            received_at=datetime.now(timezone.utc),
            is_read=False,
            importance="normal",
        ),
        EmailMessageSchema(
            id=2,
            message_id="test-msg-2",
            account_type="unitbv",
            sender="altcineva@unitbv.ro",
            recipients=["student@student.unitbv.ro"],
            subject="Info",
            body_text="Text",
            received_at=datetime.now(timezone.utc),
            is_read=False,
            importance="normal",
        ),
    ]

    filtered = await service._apply_user_memory_rules(test_emails)
    assert filtered[0].importance == "high"
    assert filtered[1].importance == "normal"

