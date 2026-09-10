import uuid
import re
from typing import List, Optional, Dict, Any
from src.app.integrations.email.factory import get_email_provider
from src.app.llm.factory import get_llm_provider
from src.app.services.practice_history_service import PracticeHistoryService
from src.app.memory.user_memory import UserMemoryService
from src.app.core.practice_config import get_practice_keywords
from src.app.core.config import settings
from src.app.schemas.email import (
    EmailMessageSchema, EmailFilterParams, EmailClassificationResult,
    EmailActionItem, EmailDraftReply
)
from src.app.core.logging import logger
from src.app.core.exceptions import HumanApprovalRequiredException, IntegrationException
from src.app.services.pending_email_draft_store import PendingEmailDraftStore


class EmailService:
    """
    Business Logic Service for Email operations.
    Decoupled from Email Provider infrastructure and FastAPI web routes.
    """

    def __init__(
        self,
        llm_provider=None,
        practice_agent=None,
        practice_history_service: Optional[PracticeHistoryService] = None,
        pending_draft_store: Optional[PendingEmailDraftStore] = None,
        user_memory_service: Optional[UserMemoryService] = None,
    ):
        self.llm = llm_provider or get_llm_provider()
        self.practice_agent = practice_agent
        self.practice_history_service = practice_history_service or PracticeHistoryService()
        self.pending_draft_store = pending_draft_store or PendingEmailDraftStore()
        self.user_memory_service = user_memory_service or UserMemoryService()

    async def list_emails(
        self,
        account_type: str = "personal",
        filter_params: Optional[EmailFilterParams] = None
    ) -> List[EmailMessageSchema]:
        provider = get_email_provider(account_type)
        emails = await provider.fetch_emails(account_type, filter_params)
        return await self._apply_user_memory_rules(emails)

    async def _apply_user_memory_rules(self, emails: List[EmailMessageSchema]) -> List[EmailMessageSchema]:
        """
        Applies long-term memory rules (Section 19: 'Mailurile de la X sunt întotdeauna importante').
        """
        try:
            memories = await self.user_memory_service.list_memories()
        except Exception:
            return emails

        if not memories:
            return emails

        important_senders = set()
        for m in memories:
            val = m.get("value", "").lower()
            found_emails = re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', val)
            if any(term in val for term in ["important", "prioritar", "urgent"]):
                for em in found_emails:
                    important_senders.add(em.lower())

        if not important_senders:
            return emails

        for email_item in emails:
            sender_clean = email_item.sender.lower()
            if any(imp in sender_clean for imp in important_senders):
                email_item.importance = "high"

        return emails

    async def search_emails(
        self,
        account_type: str = "personal",
        query: Optional[str] = None,
        sender: Optional[str] = None,
        subject: Optional[str] = None,
        days_back: Optional[int] = None,
        is_important_only: bool = False
    ) -> List[EmailMessageSchema]:
        keywords = [query] if query else None
        filter_params = EmailFilterParams(
            account_type=account_type,
            sender=sender,
            subject=subject,
            keywords=keywords,
            days_back=days_back,
            is_important_only=is_important_only
        )
        provider = get_email_provider(account_type)
        return await provider.fetch_emails(account_type, filter_params)

    async def classify_email(self, email_obj: EmailMessageSchema) -> EmailClassificationResult:
        """
        Classifies an email and detects required actions and deadlines using LLM.
        """
        prompt = (
            f"Analizează următorul e-mail și clasifică-l:\n"
            f"De la: {email_obj.sender}\n"
            f"Subiect: {email_obj.subject}\n"
            f"Conținut: {email_obj.body_text}\n\n"
            f"Identifică dacă e-mailul privește practica studențească, dacă necesită o acțiune de la student și dacă există un deadline."
        )

        system_prompt = (
            "Ești un modul de clasificare a e-mailurilor academice. "
            "Exemple de categorii: practice, academic, action_required, important, personal, informational. "
            "Răspunde structurat cu categoria, importanța (high/medium/low), motivul și eventuale deadline-uri."
        )

        try:
            llm_res = await self.llm.generate_completion(prompt=prompt, system_prompt=system_prompt)
            content = llm_res.get("content", "")

            requires_action = any(kw in content.lower() for kw in ["acțiune", "actiune", "deadline", "trimite", "completat"])
            is_practice = any(kw in (email_obj.subject + " " + email_obj.body_text).lower() for kw in ["practică", "practica", "convenție", "caiet"])
            
            category = "practice" if is_practice else ("action_required" if requires_action else "informational")
            importance = "high" if requires_action or is_practice else "medium"

            return EmailClassificationResult(
                category=category,
                importance=importance,
                reason=content[:200],
                requires_action=requires_action,
                detected_deadline=email_obj.detected_deadline,
                actions=[EmailActionItem(action="Revizuiesc mesajul de practică", priority="high")] if requires_action else []
            )
        except Exception as e:
            logger.error(f"Error classifying email: {e}")
            return EmailClassificationResult(
                category="informational",
                importance="medium",
                reason="Clasificare bazată pe fallback de securitate",
                requires_action=False
            )

    async def summarize_email(self, email_obj: EmailMessageSchema) -> str:
        """
        Generates a clear natural language summary of an email message.
        """
        if email_obj.summary and len(email_obj.summary) > 10:
            return email_obj.summary

        prompt = f"Sumarizează scurt în limba română (2-3 propoziții) e-mailul cu subiectul '{email_obj.subject}' primit de la '{email_obj.sender}':\n\n{email_obj.body_text}"
        res = await self.llm.generate_completion(prompt=prompt)
        return res.get("content", f"E-mail de la {email_obj.sender} referitor la {email_obj.subject}.")

    async def create_reply_draft(
        self,
        account_type: str,
        message_id: str,
        user_instructions: Optional[str] = None,
        owner_id: Optional[str] = None,
    ) -> EmailDraftReply:
        """
        Generates a draft reply for a specific email and registers it as pending approval.
        """
        provider = get_email_provider(account_type)
        original_email = await provider.get_email_by_id(account_type, message_id)

        # Fallback to alternate account if not found in primary
        if not original_email:
            alt_account = "unitbv" if account_type == "personal" else "personal"
            alt_provider = get_email_provider(alt_account)
            original_email = await alt_provider.get_email_by_id(alt_account, message_id)
            if original_email:
                account_type = alt_account

        if not original_email and settings.mocks_allowed:
            # Development fixtures permit a deterministic convenience fallback only.
            fallback_emails = await provider.fetch_emails(account_type, EmailFilterParams(limit=1))
            if fallback_emails:
                original_email = fallback_emails[0]
        if not original_email:
            raise IntegrationException(
                f"E-mailul cu ID '{message_id}' nu a fost găsit în contul {account_type}."
            )

        draft_metadata: Dict[str, Any] = {}
        if self._is_practice_email(original_email, user_instructions):
            practice_context = await self._build_practice_reply_context(original_email, user_instructions)
            draft_metadata = practice_context["metadata"]
            prompt = (
                f"Generează un răspuns profesional de e-mail în limba română la mesajul UNITBV despre practică.\n"
                f"Folosește exclusiv contextul oficial de mai jos și nu inventa informații.\n\n"
                f"De la: {original_email.sender}\n"
                f"Subiect: {original_email.subject}\n"
                f"Mesaj: {original_email.body_text}\n\n"
                f"Context Practice KB:\n{practice_context['answer_summary']}\n\n"
                f"Răspunsuri istorice similare:\n{practice_context['historical_context'] or 'Nu există răspunsuri istorice similare.'}\n\n"
                f"Instrucțiuni specifice de la utilizator: {user_instructions or 'Răspunde clar și concis.'}"
            )
            res = await self.llm.generate_completion(prompt=prompt)
            draft_body = res.get("content", "").strip()
            if self._is_simulated_llm_response(draft_body):
                draft_body = self._compose_practice_draft(original_email, practice_context)
        else:
            prompt = (
                f"Generează un răspuns profesional de e-mail în limba română la mesajul:\n"
                f"De la: {original_email.sender}\n"
                f"Subiect: {original_email.subject}\n"
                f"Mesaj: {original_email.body_text}\n\n"
                f"Instrucțiuni specifice de la utilizator: {user_instructions or 'Confirmă primirea și mulțumește.'}"
            )

            res = await self.llm.generate_completion(prompt=prompt)
            draft_body = res.get("content", f"Bună ziua,\n\nVă mulțumesc pentru mesaj. Am recepționat informațiile.\n\nCu stima,")

        draft_id = f"draft-{uuid.uuid4().hex[:8]}"
        draft = EmailDraftReply(
            draft_id=draft_id,
            original_message_id=original_email.message_id,
            account_type=account_type,
            recipient=original_email.sender,
            subject=f"Re: {original_email.subject}",
            body=draft_body,
            status="pending_approval",
            metadata=draft_metadata
        )

        stored_draft = await self.pending_draft_store.save(draft, owner_id)
        logger.info("Created email reply draft %s pending explicit approval.", draft_id)
        return stored_draft

    async def get_pending_draft(
        self, draft_id: str, owner_id: Optional[str] = None
    ) -> Optional[EmailDraftReply]:
        return await self.pending_draft_store.get(draft_id, owner_id)

    async def get_pending_draft_for_owner(self, owner_id: Optional[str]) -> Optional[EmailDraftReply]:
        return await self.pending_draft_store.get_for_owner(owner_id)

    async def has_pending_draft(self, owner_id: Optional[str]) -> bool:
        return await self.get_pending_draft_for_owner(owner_id) is not None

    async def send_email_after_approval(
        self,
        draft_id: str,
        approval_granted: bool,
        owner_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Human-in-the-Loop approval check. Only sends email if user explicitly approves.
        """
        draft = await self.pending_draft_store.get(draft_id, owner_id)
        if not draft:
            return {
                "status": "error",
                "message": "Draft-ul nu există, a expirat, a fost procesat sau nu aparține acestui utilizator.",
            }

        if not approval_granted:
            rejected = await self.pending_draft_store.decide(draft_id, owner_id, "rejected")
            if not rejected:
                return {"status": "error", "message": "Draft-ul nu mai poate fi anulat."}
            logger.info("User rejected email draft %s. Email was not sent.", draft_id)
            return {
                "status": "cancelled",
                "message": "Trimiterea e-mailului a fost anulată la cererea utilizatorului.",
                "draft_id": draft_id
            }

        # Claim the draft before the external side effect so duplicate Telegram updates cannot send twice.
        approved = await self.pending_draft_store.decide(draft_id, owner_id, "approved")
        if not approved:
            return {"status": "error", "message": "Draft-ul nu mai poate fi trimis."}

        provider = get_email_provider(draft.account_type)
        try:
            send_success = await provider.send_email(draft.account_type, draft)
        except Exception:
            await self.pending_draft_store.decide(
                draft_id, owner_id, "failed", expected_statuses=("approved",)
            )
            raise

        if send_success:
            await self.pending_draft_store.decide(
                draft_id, owner_id, "sent", expected_statuses=("approved",)
            )
            await self._save_practice_summary_if_needed(draft)
            return {
                "status": "sent",
                "message": f"E-mailul a fost trimis cu succes către {draft.recipient}!",
                "draft_id": draft_id
            }
        else:
            await self.pending_draft_store.decide(
                draft_id, owner_id, "failed", expected_statuses=("approved",)
            )
            return {
                "status": "failed",
                "message": f"A apărut o eroare la trimiterea e-mailului către {draft.recipient}.",
                "draft_id": draft_id
            }

    def _is_practice_email(self, email_obj: EmailMessageSchema, user_instructions: Optional[str] = None) -> bool:
        text = f"{email_obj.subject} {email_obj.body_text} {user_instructions or ''}".lower()
        base_keywords = [
            "practică", "practica", "convenție", "conventie", "caiet",
            "adeverință", "adeverinta", "colocviu", "erasmus", "tutore"
        ]
        all_keywords = set(base_keywords + get_practice_keywords())
        return email_obj.is_practice_related or any(kw.lower() in text for kw in all_keywords)

    async def _get_practice_agent(self):
        if not self.practice_agent:
            from src.app.agents.practice_agent import PracticeAgent
            self.practice_agent = PracticeAgent()
        return self.practice_agent

    async def _build_practice_reply_context(
        self,
        original_email: EmailMessageSchema,
        user_instructions: Optional[str] = None
    ) -> Dict[str, Any]:
        practice_agent = await self._get_practice_agent()
        query = f"{original_email.subject}\n{original_email.body_text}\n{user_instructions or ''}".strip()
        academic_year = practice_agent.detect_academic_year(query)
        topic = self._detect_practice_topic(query)
        question_summary = self._build_question_summary(original_email)

        rag_result = await practice_agent.handle_practice_query(query, academic_year=academic_year)
        answer_summary = self._summarize_practice_answer(rag_result)
        historical = await self.practice_history_service.find_similar(
            query=question_summary,
            academic_year=academic_year,
            limit=2,
        )
        historical_context = "\n".join(
            f"- {item.question_summary} -> {item.answer_summary}"
            for item in historical
        )

        metadata = {
            "is_practice_reply": True,
            "academic_year": academic_year,
            "topic": topic,
            "question_summary": question_summary,
            "answer_summary": answer_summary,
            "source_type": "unitbv_email",
            "source_reference": original_email.message_id,
            "student_name": self._extract_student_name(query),
            "student_group": self._extract_student_group(query),
            "decision": self._detect_decision(query, answer_summary),
            "tags": self._build_practice_tags(query),
            "rag_sources": rag_result.get("sources", []),
            "chunks_count": rag_result.get("chunks_count", 0),
        }
        return {
            "answer_summary": answer_summary,
            "historical_context": historical_context,
            "metadata": metadata,
        }

    @staticmethod
    def _detect_practice_topic(text: str) -> str:
        lowered = text.lower()
        if "erasmus" in lowered:
            return "erasmus"
        if "conven" in lowered:
            return "conventie practica"
        if "caiet" in lowered:
            return "caiet practica"
        if "adever" in lowered:
            return "adeverinta practica"
        if "colocviu" in lowered:
            return "colocviu practica"
        return "practica"

    @staticmethod
    def _build_question_summary(email_obj: EmailMessageSchema) -> str:
        base = email_obj.summary or email_obj.body_text
        return f"{email_obj.subject}: {base}".strip()[:500]

    @staticmethod
    def _summarize_practice_answer(rag_result: Dict[str, Any]) -> str:
        raw_answer = rag_result.get("raw_answer") or rag_result.get("text") or ""
        answer = raw_answer.split("📚")[0].strip()
        return answer[:900] or "Nu am găsit informația necesară în documentele disponibile."

    @staticmethod
    def _extract_student_name(text: str) -> Optional[str]:
        match = re.search(r"(?i:studentul|studenta|nume(?:\s+student)?)\s+([A-ZĂÂÎȘȚ][a-zăâîșț]+(?:\s+[A-ZĂÂÎȘȚ][a-zăâîșț]+)*)", text)
        return match.group(1).strip() if match else None

    @staticmethod
    def _extract_student_group(text: str) -> Optional[str]:
        match = re.search(r"(?i:grupa|grupă)\s+([A-Z0-9]{1,4}[- ]?[A-Z0-9]{1,4})", text)
        return match.group(1).upper().replace(" ", "-") if match else None

    @staticmethod
    def _detect_decision(query: str, answer_summary: str) -> Optional[str]:
        text = f"{query} {answer_summary}".lower()
        if "erasmus" in text and ("nu necesită" in text or "nu necesita" in text):
            return "exception_erasmus"
        if "nu am găsit" in text:
            return "insufficient_information"
        return "standard_reply"

    @staticmethod
    def _build_practice_tags(text: str) -> List[str]:
        lowered = text.lower()
        tags = []
        for tag, keywords in {
            "erasmus": ["erasmus"],
            "conventie": ["convenție", "conventie"],
            "caiet": ["caiet"],
            "adeverinta": ["adeverință", "adeverinta"],
            "colocviu": ["colocviu"],
            "deadline": ["termen", "deadline", "până", "pana"],
        }.items():
            if any(keyword in lowered for keyword in keywords):
                tags.append(tag)
        return tags or ["practica"]

    @staticmethod
    def _compose_practice_draft(original_email: EmailMessageSchema, practice_context: Dict[str, Any]) -> str:
        metadata = practice_context["metadata"]
        sources = metadata.get("rag_sources") or []
        source_lines = "\n".join(
            f"- {source.get('filename')} (pagina {source.get('page')})"
            for source in sources
        )
        source_block = f"\n\nSurse consultate:\n{source_lines}" if source_lines else ""
        return (
            "Bună ziua,\n\n"
            "Vă mulțumesc pentru mesaj. Pe baza documentelor disponibile despre practica UNITBV, răspunsul este:\n\n"
            f"{practice_context['answer_summary']}"
            f"{source_block}\n\n"
            "Cu stimă,"
        )

    @staticmethod
    def _is_simulated_llm_response(content: str) -> bool:
        return (
            not content
            or content.startswith("[Simulated Cloud LLM Response]")
            or content.startswith("[Simulated LLM Fallback]")
        )

    async def _save_practice_summary_if_needed(self, draft: EmailDraftReply) -> None:
        metadata = draft.metadata or {}
        if not metadata.get("is_practice_reply"):
            return

        await self.practice_history_service.save_exchange(
            academic_year=metadata.get("academic_year", "unknown"),
            topic=metadata.get("topic", "practica"),
            question_summary=metadata.get("question_summary", draft.subject),
            answer_summary=metadata.get("answer_summary", draft.body[:900]),
            source_type=metadata.get("source_type", "unitbv_email"),
            source_reference=metadata.get("source_reference", draft.original_message_id),
            student_name=metadata.get("student_name"),
            student_group=metadata.get("student_group"),
            decision=metadata.get("decision"),
            tags=metadata.get("tags", []),
        )
