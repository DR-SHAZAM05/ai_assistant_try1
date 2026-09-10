from typing import List, Optional
from datetime import datetime, timedelta, timezone
from src.app.integrations.email.base import EmailProvider
from src.app.schemas.email import EmailMessageSchema, EmailFilterParams, EmailDraftReply
from src.app.core.logging import logger

now = datetime.now(timezone.utc)

MOCK_EMAILS: List[EmailMessageSchema] = [
    EmailMessageSchema(
        id=1,
        message_id="msg-unitbv-101",
        account_type="unitbv",
        sender="responsabil.practica@unitbv.ro",
        recipients=["student.unitbv@student.unitbv.ro"],
        subject="Practică UNITBV – Convenție și Caiet de Practică 2026-2027",
        body_text="București/Brașov, Vă rugăm să trimiteți convenția de practică completată și semnată de tutorele de la companie până pe data de 28 august 2026.",
        received_at=now - timedelta(hours=2),
        summary="Responsabilul de practică solicită convenția semnată până pe 28 august 2026.",
        category="practice",
        importance="high",
        is_practice_related=True,
        requires_action=True,
        detected_deadline="2026-08-28"
    ),
    EmailMessageSchema(
        id=2,
        message_id="msg-unitbv-102",
        account_type="unitbv",
        sender="secretariat.fiesc@unitbv.ro",
        recipients=["student.unitbv@student.unitbv.ro"],
        subject="Anunț colocviu de practică și adeverințe",
        body_text="Colocviul de practică va avea loc în data de 5 septembrie 2026. Adeverința cu numărul de ore efectuate trebuie încărcată pe platformă cu 3 zile înainte.",
        received_at=now - timedelta(hours=5),
        summary="Anunț referitor la data colocviului de practică și termenul pentru adeverință.",
        category="practice",
        importance="medium",
        is_practice_related=True,
        requires_action=True,
        detected_deadline="2026-09-02"
    ),
    EmailMessageSchema(
        id=3,
        message_id="msg-personal-201",
        account_type="personal",
        sender="newsletter@tech-today.org",
        recipients=["user.personal@example.com"],
        subject="Weekly Tech Digest - Open Source AI Frameworks",
        body_text="Here are top trending repositories in AI agents, RAG engines, and vector databases this week.",
        received_at=now - timedelta(hours=8),
        summary="Newsletter săptămânal despre tendințele în AI și tehnologie.",
        category="informational",
        importance="low",
        is_practice_related=False,
        requires_action=False
    ),
    EmailMessageSchema(
        id=4,
        message_id="msg-personal-202",
        account_type="personal",
        sender="banca@mybank.ro",
        recipients=["user.personal@example.com"],
        subject="Extras de cont lunar disponibil",
        body_text="Extrasul tău de cont pentru luna iulie 2026 a fost generat și este disponibil în format PDF.",
        received_at=now - timedelta(days=1),
        summary="Notificare extras de cont lunar.",
        category="personal",
        importance="medium",
        is_practice_related=False,
        requires_action=False
    )
]


class MockEmailProvider(EmailProvider):
    """
    Mock Email Provider for local development and deterministic testing.
    """

    def __init__(self):
        self._storage: List[EmailMessageSchema] = list(MOCK_EMAILS)
        self.sent_emails: List[EmailDraftReply] = []

    async def fetch_emails(
        self,
        account_type: str,
        filter_params: Optional[EmailFilterParams] = None
    ) -> List[EmailMessageSchema]:
        results = [e for e in self._storage if e.account_type.lower() == account_type.lower()]

        if not filter_params:
            return results

        if filter_params.sender:
            results = [e for e in results if filter_params.sender.lower() in e.sender.lower()]

        if filter_params.subject:
            results = [e for e in results if filter_params.subject.lower() in e.subject.lower()]

        if filter_params.keywords:
            filtered = []
            for e in results:
                text_content = f"{e.subject} {e.body_text}".lower()
                if any(kw.lower() in text_content for kw in filter_params.keywords):
                    filtered.append(e)
            results = filtered

        if filter_params.is_important_only:
            results = [e for e in results if e.importance in ["high", "important"]]

        if filter_params.days_back:
            cutoff = now - timedelta(days=filter_params.days_back)
            results = [e for e in results if e.received_at >= cutoff]

        return results[:filter_params.limit]

    async def get_email_by_id(
        self,
        account_type: str,
        message_id: str
    ) -> Optional[EmailMessageSchema]:
        for e in self._storage:
            if e.account_type.lower() == account_type.lower() and (e.message_id == message_id or str(e.id) == str(message_id)):
                return e
        return None

    async def send_email(
        self,
        account_type: str,
        draft: EmailDraftReply
    ) -> bool:
        logger.info(f"[MockEmailProvider Send] Account: {account_type} | To: {draft.recipient} | Subject: {draft.subject}")
        draft.status = "sent"
        self.sent_emails.append(draft)
        return True
