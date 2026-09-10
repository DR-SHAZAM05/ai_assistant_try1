import pytest
from src.app.agents.email_agent import EmailAgent
from src.app.services.email_service import EmailService
from src.app.integrations.email.mock_provider import MockEmailProvider
from src.app.schemas.email import EmailMessageSchema


class FakePracticeAgent:
    def detect_academic_year(self, user_prompt: str) -> str:
        return "2026-2027"

    async def handle_practice_query(self, user_prompt: str, academic_year=None):
        return {
            "raw_answer": "Studentul trebuie să trimită convenția de practică până la 28 august 2026.",
            "text": "Studentul trebuie să trimită convenția de practică până la 28 august 2026.",
            "sources": [{"filename": "Ghid_Practica_2026_2027.md", "page": 1}],
            "chunks_count": 1,
            "academic_year": academic_year or "2026-2027",
        }


class FakePracticeHistoryService:
    def __init__(self):
        self.saved = []

    async def find_similar(self, **kwargs):
        return []

    async def save_exchange(self, **kwargs):
        self.saved.append(kwargs)
        return kwargs


@pytest.mark.asyncio
async def test_email_service_list_emails():
    service = EmailService()
    unitbv_emails = await service.list_emails(account_type="unitbv")
    assert len(unitbv_emails) > 0
    assert all(e.account_type == "unitbv" for e in unitbv_emails)

    personal_emails = await service.list_emails(account_type="personal")
    assert len(personal_emails) > 0
    assert all(e.account_type == "personal" for e in personal_emails)


@pytest.mark.asyncio
async def test_email_agent_query_unitbv():
    agent = EmailAgent()
    res = await agent.handle_email_query("Arată-mi mailurile de pe UNITBV.", account_type="unitbv")
    assert res["account"] == "unitbv"
    assert "E-mailuri primite pe contul UNITBV" in res["text"]
    assert res["count"] > 0


@pytest.mark.asyncio
async def test_email_agent_action_items():
    agent = EmailAgent()
    res = await agent.handle_action_items_query("Ce am de făcut din mailurile de practică?", account_type="unitbv")
    assert "actions" in res
    assert len(res["actions"]) > 0


@pytest.mark.asyncio
async def test_email_draft_and_approval_flow():
    agent = EmailAgent()

    # 1. Generate Draft
    draft_res = await agent.handle_draft_reply("Răspunde la mailul de practică", account_type="unitbv", message_id="msg-unitbv-101")
    assert draft_res["status"] == "pending_approval"
    draft_id = draft_res["draft_id"]

    # 2. Reject sending ("Nu")
    rejection = await agent.handle_approval(draft_id=draft_id, approval_granted=False)
    assert rejection["status"] == "cancelled"

    # 3. Create another draft and approve ("Da")
    draft_res2 = await agent.handle_draft_reply("Răspunde la mailul de practică", account_type="unitbv", message_id="msg-unitbv-101")
    draft_id2 = draft_res2["draft_id"]
    approval = await agent.handle_approval(draft_id=draft_id2, approval_granted=True)
    assert approval["status"] == "sent"


@pytest.mark.asyncio
async def test_email_draft_approval_is_scoped_to_its_owner():
    agent = EmailAgent()
    draft_res = await agent.handle_draft_reply(
        "Răspunde la mailul de practică",
        account_type="unitbv",
        message_id="msg-unitbv-101",
        owner_id="telegram-user-a",
    )

    unauthorized = await agent.handle_approval(
        draft_id=draft_res["draft_id"],
        approval_granted=True,
        owner_id="telegram-user-b",
    )
    assert unauthorized["status"] == "error"

    owner_rejection = await agent.handle_approval(
        draft_id=draft_res["draft_id"],
        approval_granted=False,
        owner_id="telegram-user-a",
    )
    assert owner_rejection["status"] == "cancelled"


@pytest.mark.asyncio
async def test_practice_email_draft_uses_rag_and_saves_history_after_approval():
    history = FakePracticeHistoryService()
    service = EmailService(
        practice_agent=FakePracticeAgent(),
        practice_history_service=history,
    )
    agent = EmailAgent(email_service=service)

    draft_res = await agent.handle_draft_reply(
        "Răspunde la mailul de practică folosind ghidul oficial.",
        account_type="unitbv",
        message_id="msg-unitbv-101",
    )

    draft = await service.get_pending_draft(draft_res["draft_id"])
    assert draft is not None
    assert draft.metadata["is_practice_reply"] is True
    assert draft.metadata["academic_year"] == "2026-2027"
    assert draft.metadata["topic"] == "conventie practica"
    assert "28 august 2026" in draft.body
    assert history.saved == []

    approval = await agent.handle_approval(draft_id=draft.draft_id, approval_granted=True)

    assert approval["status"] == "sent"
    assert len(history.saved) == 1
    assert history.saved[0]["source_type"] == "unitbv_email"
    assert history.saved[0]["source_reference"] == "msg-unitbv-101"
    assert "convenția" in history.saved[0]["answer_summary"]


def test_practice_metadata_extraction_helpers():
    service = EmailService()
    text = "Studentul Popescu Ion de la grupa 4LF211 întreabă despre convenție și colocviu de practică."
    assert service._detect_practice_topic(text) in ["conventie practica", "colocviu practica"]
    assert service._extract_student_name(text) == "Popescu Ion"
    assert service._extract_student_group(text) == "4LF211"
    tags = service._build_practice_tags(text)
    assert "conventie" in tags
    assert "colocviu" in tags


def test_message_id_extraction_requires_an_explicit_identifier():
    assert EmailAgent._extract_message_id("Răspunde la mailul folosind ghidul oficial") is None
    assert EmailAgent._extract_message_id("Răspunde la mesajul cu ID msg-unitbv-101") == "msg-unitbv-101"
