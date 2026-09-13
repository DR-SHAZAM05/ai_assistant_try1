import re
from typing import Dict, Any, List, Optional
from src.app.services.email_service import EmailService
from src.app.services.action_item_service import ActionItemService
from src.app.schemas.email import EmailFilterParams
from src.app.core.config import settings
from src.app.core.logging import logger


class EmailAgent:
    """
    Specialized Email Agent. Handles email search, classification, summarization,
    action items detection, draft reply creation, and Human-in-the-Loop confirmation.
    """

    def __init__(
        self,
        email_service: Optional[EmailService] = None,
        action_item_service: Optional[ActionItemService] = None,
    ):
        self.email_service = email_service or EmailService()
        self.action_item_service = action_item_service or ActionItemService()

    def determine_account_type(self, user_prompt: str) -> str:
        """
        Determines target account type ('unitbv' or 'personal') from user prompt text.
        """
        prompt_lower = user_prompt.lower()
        if "unitbv" in prompt_lower or "facultate" in prompt_lower or "student" in prompt_lower or "practica" in prompt_lower or "practică" in prompt_lower:
            return "unitbv"
        elif "personal" in prompt_lower:
            return "personal"
        else:
            return "personal"

    async def handle_email_query(
        self,
        user_prompt: str,
        account_type: Optional[str] = None,
        is_important_only: bool = False,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Handles general email search/list requests.
        """
        target_account = account_type or self.determine_account_type(user_prompt)
        logger.info(f"EmailAgent fetching emails for account '{target_account}'...")

        try:
            emails = await self.email_service.list_emails(
                account_type=target_account,
                filter_params=EmailFilterParams(account_type=target_account, is_important_only=is_important_only, limit=5),
                user_id=user_id,
            )
        except Exception as exc:
            logger.warning("Email service unavailable for %s (%s): %s", target_account, type(exc).__name__, exc)
            return {
                "text": (
                    f"⚠️ Nu am putut accesa căsuța de e-mail **{target_account.upper()}**.\n"
                    f"Cauză: {exc}\n\n"
                    "Dacă este contul instituțional UNITBV (Office 365), verifică dacă autentificarea IMAP cu parolă simplă nu a fost blocată de Microsoft Entra ID."
                ),
                "count": 0,
                "account": target_account,
                "status": "error"
            }

        if not emails:
            return {
                "text": f"📥 Nu am găsit e-mailuri noi pe contul **{target_account.upper()}**.",
                "count": 0,
                "account": target_account
            }

        # Build user-friendly Telegram response
        formatted_lines = [f"📧 **E-mailuri primite pe contul {target_account.upper()}**:\n"]
        for idx, mail in enumerate(emails, 1):
            imp_tag = "🔴 [IMPORTANT]" if mail.importance in ["high", "important"] or mail.is_practice_related else "🔵 [INFO]"
            formatted_lines.append(f"{idx}. {imp_tag}")
            formatted_lines.append(f"   **De la**: `{mail.sender}`")
            formatted_lines.append(f"   **Subiect**: {mail.subject}")
            formatted_lines.append(f"   **ID mesaj**: `{mail.message_id}`")
            formatted_lines.append(f"   **Sumar**: {mail.summary or mail.body_text[:120]}...")
            if mail.detected_deadline:
                formatted_lines.append(f"   **Deadline detectat**: {mail.detected_deadline}")
            formatted_lines.append("")

        return {
            "text": "\n".join(formatted_lines),
            "count": len(emails),
            "account": target_account,
            "emails": [e.model_dump() for e in emails]
        }

    async def handle_action_items_query(
        self,
        user_prompt: str,
        account_type: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Extracts action items and deadlines from emails.
        """
        target_account = account_type or self.determine_account_type(user_prompt)
        try:
            emails = await self.email_service.list_emails(
                account_type=target_account,
                filter_params=EmailFilterParams(account_type=target_account, limit=10),
                user_id=user_id,
            )
        except Exception as exc:
            logger.warning("Email service unavailable for action items (%s): %s", target_account, exc)
            return {
                "text": f"⚠️ Nu am putut accesa căsuța de e-mail **{target_account.upper()}** pentru extragerea de acțiuni ({exc}).",
                "actions": []
            }

        actions_found = []
        for e in emails:
            if e.requires_action or e.is_practice_related or e.detected_deadline:
                action_title = f"Răspunde / acțiune necesară: {e.subject}"
                priority = "high" if e.importance in ["high", "important"] or e.is_practice_related else "medium"

                deadline_dt = None
                if e.detected_deadline:
                    try:
                        from dateutil import parser as dt_parser
                        deadline_dt = dt_parser.parse(e.detected_deadline)
                    except Exception:
                        pass

                saved_item = await self.action_item_service.create_action_item(
                    title=action_title,
                    source=f"email_{target_account}",
                    deadline=deadline_dt,
                    priority=priority,
                    source_reference=e.message_id,
                    user_id=user_id,
                )

                actions_found.append({
                    "id": saved_item.get("id"),
                    "subject": e.subject,
                    "sender": e.sender,
                    "deadline": e.detected_deadline or "Nespecificat",
                    "priority": priority,
                    "action": action_title
                })

        if not actions_found:
            return {
                "text": f"✅ Nu ai acțiuni sau deadline-uri urgente pe contul **{target_account.upper()}**.",
                "actions": []
            }

        lines = [f"📋 **Acțiuni și Deadline-uri extrase din e-mailurile {target_account.upper()}**:\n"]
        for idx, act in enumerate(actions_found, 1):
            pri_emoji = "🔴" if act["priority"] == "high" else "🟡"
            task_id_str = f" [Task #{act['id']}]" if act.get("id") else ""
            lines.append(f"{idx}. {pri_emoji} **{act['action']}**{task_id_str}")
            lines.append(f"   • Subiect: _{act['subject']}_")
            lines.append(f"   • Expeditor: `{act['sender']}`")
            lines.append(f"   • Deadline: `{act['deadline']}`")
            lines.append("")

        lines.append("💾 *Sarcinile au fost salvate în baza de date.* Poți întreba oricând: *„Ce sarcini am?”*")

        return {
            "text": "\n".join(lines),
            "actions": actions_found
        }

    async def handle_draft_reply(
        self,
        user_prompt: str,
        account_type: Optional[str] = None,
        message_id: Optional[str] = None,
        owner_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generates draft reply and prepares Human-in-the-Loop Telegram prompt.
        """
        target_account = account_type or self.determine_account_type(user_prompt)
        target_msg_id = message_id or self._extract_message_id(user_prompt)

        # Smart resolution: support 'mailul 1', 'primul mail', sender names, or latest email
        if not target_msg_id:
            try:
                recent_emails = await self.email_service.list_emails(
                    account_type=target_account,
                    filter_params=EmailFilterParams(account_type=target_account, limit=10),
                    user_id=owner_id,
                )
                if recent_emails:
                    idx_match = re.search(r"(?i)\b(?:mailul|emailul|mesajul|nr\.?)\s*(\d+)\b", user_prompt)
                    if idx_match:
                        idx = int(idx_match.group(1)) - 1
                        if 0 <= idx < len(recent_emails):
                            target_msg_id = recent_emails[idx].message_id
                    elif any(w in user_prompt.lower() for w in ["primul mail", "primul mesaj", "primul email"]):
                        target_msg_id = recent_emails[0].message_id
                    elif any(w in user_prompt.lower() for w in ["ultimul mail", "ultimul mesaj", "ultimul email"]):
                        target_msg_id = recent_emails[0].message_id
                    else:
                        for em in recent_emails:
                            sender_tokens = re.findall(r"[a-zA-Z0-9]+", em.sender.lower())
                            if any(tok in user_prompt.lower() for tok in sender_tokens if len(tok) >= 4):
                                target_msg_id = em.message_id
                                break

                    # Default to latest email if user just asked to reply
                    if not target_msg_id:
                        target_msg_id = recent_emails[0].message_id
            except Exception as exc:
                logger.warning("Could not auto-resolve target email for reply: %s", exc)

        if not target_msg_id and settings.mocks_allowed:
            target_msg_id = "msg-unitbv-101"
        if not target_msg_id:
            return {
                "text": "Nu am putut identifica e-mailul la care dorești să răspunzi. Specifică numărul mesajului (ex. 'mailul 1') sau adresa expeditorului.",
                "status": "needs_message_selection",
            }

        draft = await self.email_service.create_reply_draft(
            account_type=target_account,
            message_id=target_msg_id,
            user_instructions=user_prompt,
            owner_id=owner_id,
        )

        prompt_text = (
            f"✏️ **Am pregătit următorul draft de răspuns**:\n\n"
            f"**Către**: `{draft.recipient}`\n"
            f"**Subiect**: {draft.subject}\n"
            f"**Mesaj**:\n```\n{draft.body}\n```\n\n"
            f"⚠️ **Confirmare umană necesară**: Doriți să trimit acest e-mail?\n"
            f"Răspundeți cu **[Da]** pentru trimitere sau **[Nu]** pentru anulare."
        )

        return {
            "text": prompt_text,
            "draft_id": draft.draft_id,
            "status": "pending_approval",
            "recipient": draft.recipient
        }

    async def handle_approval(
        self,
        draft_id: str,
        approval_granted: bool,
        owner_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Processes human confirmation (Da/Nu) for an email draft.
        """
        result = await self.email_service.send_email_after_approval(
            draft_id, approval_granted, owner_id=owner_id
        )
        return {
            "text": result["message"],
            "status": result["status"]
        }

    async def get_pending_draft_for_owner(self, owner_id: Optional[str]):
        return await self.email_service.get_pending_draft_for_owner(owner_id)

    async def has_pending_draft(self, owner_id: Optional[str]) -> bool:
        return await self.email_service.has_pending_draft(owner_id)

    @staticmethod
    def _extract_message_id(user_prompt: str) -> Optional[str]:
        match = re.search(
            r"(?i)(?:\bid(?:\s+mesaj)?\b|\bmessage[_ -]?id\b)\s*[:#]?\s*(`?[^\s`]+`?)",
            user_prompt,
        )
        return match.group(1).strip("`") if match else None
