from typing import List, Dict, Any, Optional
from src.app.llm.base import LLMProvider
from src.app.llm.factory import get_llm_provider
from src.app.orchestrator.intent import IntentType, IntentDetectionResult
from src.app.orchestrator.tool_registry import global_tool_registry
from src.app.agents.email_agent import EmailAgent
from src.app.agents.calendar_agent import CalendarAgent
from src.app.agents.news_agent import NewsAgent
from src.app.agents.practice_agent import PracticeAgent
from src.app.services.action_item_service import ActionItemService
from src.app.services.audit_service import AuditService
from src.app.services.document_generator_service import DocumentGeneratorService
from src.app.services.news_service import NewsService
from src.app.memory.user_memory import UserMemoryService
from src.app.schemas.email import EmailFilterParams
from src.app.integrations.telegram.service import (
    get_draft_approval_keyboard,
    get_tasks_action_keyboard,
    get_email_action_keyboard,
    get_documents_download_keyboard,
)
from src.app.core.config import settings
from src.app.core.logging import logger
from src.app.core.practice_config import get_practice_deadlines, get_current_academic_year
from src.app.core.user_scope import require_user_id

# Active pending drafts map by user_id
_user_pending_draft_map: Dict[str, str] = {}


class AIOrchestrator:
    """
    Central AI Orchestrator responsible for intent detection, tool routing,
    executing Email, Calendar, News, Practice RAG, Action Items, and Document Generation Agents,
    managing Long-Term User Memory & Preferences, and Human-in-the-Loop state.
    """

    def __init__(
        self,
        llm_provider: Optional[LLMProvider] = None,
        email_agent: Optional[EmailAgent] = None,
        calendar_agent: Optional[CalendarAgent] = None,
        news_agent: Optional[NewsAgent] = None,
        practice_agent: Optional[PracticeAgent] = None,
        action_item_service: Optional[ActionItemService] = None,
        audit_service: Optional[AuditService] = None,
        document_generator_service: Optional[DocumentGeneratorService] = None,
        user_memory_service: Optional[UserMemoryService] = None,
    ):
        self.llm = llm_provider or get_llm_provider()
        self.email_agent = email_agent or EmailAgent()
        self.calendar_agent = calendar_agent or CalendarAgent()
        self.news_agent = news_agent or NewsAgent()
        self.practice_agent = practice_agent or PracticeAgent()
        self.action_item_service = action_item_service or ActionItemService()
        self.audit_service = audit_service or AuditService()
        self.document_generator_service = document_generator_service or DocumentGeneratorService()
        self.user_memory_service = user_memory_service or UserMemoryService()
        self.tool_registry = global_tool_registry
        self._register_default_tools()

    def _register_default_tools(self):
        """Register email, calendar, news, practice, and task tools in ToolRegistry."""
        try:
            # Task tools
            self.tool_registry.register_tool(
                name="tasks_list",
                description="List open tasks and action items from PostgreSQL database.",
                func=self.action_item_service.list_action_items
            )
            # Email tools
            self.tool_registry.register_tool(
                name="email_search",
                description="Search and list emails from personal or UNITBV account.",
                func=self.email_agent.handle_email_query
            )
            self.tool_registry.register_tool(
                name="email_draft_reply",
                description="Generate a draft reply for an email.",
                func=self.email_agent.handle_draft_reply
            )
            self.tool_registry.register_tool(
                name="email_send",
                description="Send email after explicit human approval.",
                func=self.email_agent.handle_approval
            )
            # Calendar tools
            self.tool_registry.register_tool(
                name="calendar_search",
                description="Fetch calendar events for natural language date ranges.",
                func=self.calendar_agent.handle_calendar_query
            )
            # News tools
            self.tool_registry.register_tool(
                name="news_search",
                description="Fetch deduplicated, scored news articles by topic.",
                func=self.news_agent.handle_news_query
            )
            # Practice RAG tools
            self.tool_registry.register_tool(
                name="practice_search",
                description="Query practice knowledge base using semantic RAG search.",
                func=self.practice_agent.handle_practice_query
            )
            # Long-term User Memory tools
            self.tool_registry.register_tool(
                name="memory_save",
                description="Save long-term user preference or rule in persistent memory.",
                func=self.user_memory_service.set_memory
            )
            self.tool_registry.register_tool(
                name="memory_list",
                description="List stored user preferences and rules.",
                func=self.user_memory_service.list_memories
            )
        except Exception as e:
            logger.debug(f"Tools registration note: {e}")

    async def detect_intent(
        self,
        user_prompt: str,
        user_id: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> IntentDetectionResult:
        """
        Detects user intent from natural language input.
        Practice RAG questions take priority when practice domain keywords are detected.
        """
        prompt_clean = user_prompt.strip(" .!?,;:\n").lower()
        uid = require_user_id(user_id)

        # 0. Direct button menu & slash command matches
        button_map = {
            "📄 convenție practică": (IntentType.PRACTICE_DOCUMENT_REQUEST, ["document_generator_service"]),
            "📄 conventie practica": (IntentType.PRACTICE_DOCUMENT_REQUEST, ["document_generator_service"]),
            "📘 caiet de practică": (IntentType.PRACTICE_DOCUMENT_REQUEST, ["document_generator_service"]),
            "📘 caiet de practica": (IntentType.PRACTICE_DOCUMENT_REQUEST, ["document_generator_service"]),
            "📋 sarcinile mele": (IntentType.TASKS_QUERY, ["action_item_service"]),
            "📅 program calendar": (IntentType.CALENDAR_QUERY, ["calendar_agent"]),
            "📧 verifică emailuri": (IntentType.EMAIL_QUERY, ["email_agent"]),
            "📧 verifica emailuri": (IntentType.EMAIL_QUERY, ["email_agent"]),
            "📰 știri tehnologice": (IntentType.NEWS_QUERY, ["news_agent"]),
            "📰 stiri tehnologice": (IntentType.NEWS_QUERY, ["news_agent"]),
            "/conventie": (IntentType.PRACTICE_DOCUMENT_REQUEST, ["document_generator_service"]),
            "/caiet": (IntentType.PRACTICE_DOCUMENT_REQUEST, ["document_generator_service"]),
            "/documente": (IntentType.PRACTICE_DOCUMENT_REQUEST, ["document_generator_service"]),
            "/sarcini": (IntentType.TASKS_QUERY, ["action_item_service"]),
            "/calendar": (IntentType.CALENDAR_QUERY, ["calendar_agent"]),
            "/email": (IntentType.EMAIL_QUERY, ["email_agent"]),
            "/stiri": (IntentType.NEWS_QUERY, ["news_agent"]),
            "/briefing": (IntentType.DAILY_BRIEFING, ["calendar_agent", "action_item_service", "news_agent"]),
            "/sinteza": (IntentType.AGGREGATED_OVERVIEW, ["calendar_agent", "action_item_service", "email_agent", "practice_agent"]),
            "/overview": (IntentType.AGGREGATED_OVERVIEW, ["calendar_agent", "action_item_service", "email_agent", "practice_agent"]),
            "/practice": (IntentType.PRACTICE_QUERY, ["practice_agent"]),
            "/practica": (IntentType.PRACTICE_QUERY, ["practice_agent"]),
            "/memorie": (IntentType.MEMORY_MANAGE, ["user_memory_service"]),
            "/preferinte": (IntentType.MEMORY_MANAGE, ["user_memory_service"]),
            "/reguli": (IntentType.MEMORY_MANAGE, ["user_memory_service"]),
            "🌅 briefing matinal": (IntentType.DAILY_BRIEFING, ["calendar_agent", "action_item_service", "news_agent"]),
            "🧠 preferințe și reguli": (IntentType.MEMORY_MANAGE, ["user_memory_service"]),
            "🧠 preferinte si reguli": (IntentType.MEMORY_MANAGE, ["user_memory_service"]),
        }
        if prompt_clean in button_map:
            intent, targets = button_map[prompt_clean]
            return IntentDetectionResult(
                intent=intent,
                confidence=1.0,
                target_agents=targets,
            )

        # 0.5 Telegram inline callback queries
        if prompt_clean.startswith("approve_draft:") or prompt_clean.startswith("reject_draft:"):
            return IntentDetectionResult(
                intent=IntentType.EMAIL_SEND_CONFIRMATION,
                confidence=1.0,
                target_agents=["email_agent"]
            )
        if prompt_clean.startswith("complete_task:"):
            return IntentDetectionResult(
                intent=IntentType.TASKS_QUERY,
                confidence=1.0,
                target_agents=["action_item_service"]
            )
        if prompt_clean.startswith("draft_reply:") or prompt_clean.startswith("reply_mail:"):
            return IntentDetectionResult(
                intent=IntentType.EMAIL_DRAFT_REPLY,
                confidence=1.0,
                target_agents=["email_agent"]
            )
        if prompt_clean in ["conventie_download", "caiet_download", "all_docs_download"]:
            return IntentDetectionResult(
                intent=IntentType.PRACTICE_DOCUMENT_REQUEST,
                confidence=1.0,
                target_agents=["document_generator_service"]
            )

        # 1. Pending draft confirmation ("da" / "nu")
        if prompt_clean in ["da", "nu", "yes", "no", "trimite", "anulează", "anuleaza"]:
            has_pending_draft = uid in _user_pending_draft_map or await self.email_agent.has_pending_draft(uid)
            if has_pending_draft:
                return IntentDetectionResult(
                    intent=IntentType.EMAIL_SEND_CONFIRMATION,
                    confidence=1.0,
                    target_agents=["email_agent"]
                )

        # 1.5 Calendar Add / Schedule Event
        cal_add_verbs = [
            "adaugă în calendar", "adauga in calendar", "programează în calendar", "programeaza in calendar",
            "pune în calendar", "pune in calendar", "trece în calendar", "trece in calendar",
            "adaugă eveniment", "adauga eveniment", "programează o ședință", "programeaza o sedinta",
            "programează o întâlnire", "programeaza o intalnire", "adaugă o ședință", "adauga o sedinta"
        ]
        if any(v in prompt_clean for v in cal_add_verbs):
            return IntentDetectionResult(
                intent=IntentType.CALENDAR_ADD_EVENT,
                confidence=0.98,
                target_agents=["calendar_agent"]
            )

        # 2. Practice Document Generation / Download (Convenție cadru, Caiet de practică DOCX)
        doc_gen_verbs = [
            "generează", "genereaza", "descarcă", "descarca", "creează", "creeaza",
            "fă-mi", "fa-mi", "descarc", "vreau", "dă-mi", "da-mi", "trimite-mi", "exportă", "exporta"
        ]
        doc_targets = [
            "conventi", "convenț", "conventie", "convenție", "caiet", "caietul", "jurnal", "jurnalul",
            "documentele de practică", "documentele de practica", "dosarul de practică", "dosarul de practica"
        ]
        is_asking_doc = any(v in prompt_clean for v in doc_gen_verbs) or ("docx" in prompt_clean) or ("word" in prompt_clean)
        has_doc_target = any(t in prompt_clean for t in doc_targets)
        is_info_question = any(prompt_clean.startswith(q) for q in ["când", "cand", "cum", "care", "unde", "cât", "cat", "ce este"])

        if has_doc_target and (is_asking_doc or any(prompt_clean.startswith(p) for p in ["vreau conventia", "vreau convenția", "vreau caietul", "da-mi conventia", "dă-mi convenția", "da-mi caietul", "dă-mi caietul"])) and not (is_info_question and not ("genereaza" in prompt_clean or "generează" in prompt_clean or "descarca" in prompt_clean or "descarcă" in prompt_clean)):
            return IntentDetectionResult(
                intent=IntentType.PRACTICE_DOCUMENT_REQUEST,
                confidence=0.98,
                target_agents=["document_generator_service"]
            )

        # 3. Practice RAG queries
        practice_keywords = ["practica", "practică", "procedura", "procedură", "conventie", "convenție", "caiet de practica", "caiet de practică", "erasmus", "colocviu practica", "colocviu practică", "regulament practica", "regulament practică"]
        practice_history_keywords = ["ce am raspuns", "ce am răspuns", "raspuns istoric", "răspuns istoric", "raspunsuri istorice", "răspunsuri istorice", "anul trecut", "anul anterior"]
        if any(kw in prompt_clean for kw in practice_keywords):
            # Distinguish email practice check from RAG practice rules
            if not any(e_kw in prompt_clean for e_kw in ["mail", "email", "inbox", "primite"]):
                if any(hist_kw in prompt_clean for hist_kw in practice_history_keywords):
                    return IntentDetectionResult(
                        intent=IntentType.PRACTICE_HISTORY_QUERY,
                        confidence=0.95,
                        target_agents=["practice_agent"]
                    )
                return IntentDetectionResult(
                    intent=IntentType.PRACTICE_QUERY,
                    confidence=0.95,
                    target_agents=["practice_agent"]
                )

        # Check follow-up context from recent conversation history
        if history and len(prompt_clean.split()) <= 7:
            recent_texts = " ".join([m.get("content", "").lower() for m in history[-2:]])
            if any(kw in recent_texts for kw in practice_keywords):
                other_domain_keywords = ["mail", "email", "stiri", "știri", "vremea", "meteo", "eveniment", "orar"]
                if not any(dk in prompt_clean for dk in other_domain_keywords):
                    return IntentDetectionResult(
                        intent=IntentType.PRACTICE_QUERY,
                        confidence=0.85,
                        target_agents=["practice_agent"]
                    )

        # 3. Email draft reply
        draft_keywords = [
            "răspunde", "raspunde", "draft", "compune raspuns", "compune răspuns",
            "compune", "generează draft", "genereaza draft", "scrie raspuns", "scrie răspuns"
        ]
        if any(kw in prompt_clean for kw in draft_keywords):
            return IntentDetectionResult(
                intent=IntentType.EMAIL_DRAFT_REPLY,
                confidence=0.95,
                target_agents=["email_agent"]
            )

        # 4. Email action items
        if any(kw in prompt_clean for kw in ["ce trebuie să fac din mailuri", "ce am de făcut din mailuri", "actiuni mail", "acțiuni mail"]):
            return IntentDetectionResult(
                intent=IntentType.EMAIL_ACTION_ITEMS,
                confidence=0.95,
                target_agents=["email_agent"]
            )

        # 5. Email queries / search
        email_keywords = ["mail", "email", "inbox", "expeditor", "mesaje primite", "ce am primit"]
        if any(kw in prompt_clean for kw in email_keywords):
            return IntentDetectionResult(
                intent=IntentType.EMAIL_QUERY,
                confidence=0.9,
                target_agents=["email_agent"]
            )

        # 6. News queries
        if any(kw in prompt_clean for kw in ["stiri", "știri", "news", "articole", "ce s-a mai întâmplat", "ce noutăți"]):
            return IntentDetectionResult(
                intent=IntentType.NEWS_QUERY,
                confidence=0.95,
                target_agents=["news_agent"]
            )

        # 7. Date and Time quick queries
        date_time_questions = [
            "ce zi este", "ce zi e", "în ce zi suntem", "in ce zi suntem",
            "ce dată este", "ce data este", "ce dată e", "ce data e",
            "ce data avem", "ce dată avem", "data de azi", "data de astăzi",
            "cât e ceasul", "cat e ceasul", "ce oră este", "ce ora este", "ce oră e", "ce ora e"
        ]
        if any(dq in prompt_clean for dq in date_time_questions):
            return IntentDetectionResult(
                intent=IntentType.GENERAL_QUERY,
                confidence=0.98,
                target_agents=[]
            )

        # 8. Weather / Meteo quick queries
        weather_keywords = [
            "vremea", "meteo", "temperatura", "temperatură",
            "ploua", "plouă", "ninge", "date meteorologice", "datele meteorologice",
            "prognoza", "prognoză", "prognoza meteo", "prognoză meteo"
        ]
        if any(wk in prompt_clean for wk in weather_keywords):
            return IntentDetectionResult(
                intent=IntentType.GENERAL_QUERY,
                confidence=0.98,
                target_agents=[]
            )

        # 9. Long-term User Memory / Preferences
        memory_store_triggers = [
            "ține minte că", "tine minte ca", "ține minte ca", "tine minte că",
            "prefer să", "prefer sa",
            "reține că", "retine ca", "reține regula", "retine regula",
            "memorează că", "memoreaza ca",
            "salvează preferința", "salveaza preferinta", "salvează regula", "salveaza regula"
        ]
        memory_query_triggers = [
            "ce preferințe ai salvate", "ce preferinte ai salvate",
            "ce preferințe am", "ce preferinte am", "ce preferințe ai", "ce preferinte ai",
            "ce reguli ai memorat", "ce reguli am", "ce reguli ai salvate", "ce reguli ai",
            "ce ții minte despre mine", "ce tii minte despre mine",
            "ce memorie ai", "ce reguli cunoști", "ce reguli cunosti",
            "ce ai memorat", "ce preferințe sunt salvate"
        ]
        memory_clear_triggers = [
            "șterge memoria", "sterge memoria", "uită tot", "uita tot",
            "șterge preferințele", "sterge preferintele", "resetează memoria", "reseteaza memoria"
        ]
        if (
            any(t in prompt_clean for t in memory_store_triggers)
            or any(t in prompt_clean for t in memory_query_triggers)
            or any(t in prompt_clean for t in memory_clear_triggers)
        ):
            return IntentDetectionResult(
                intent=IntentType.MEMORY_MANAGE,
                confidence=0.98,
                target_agents=["user_memory_service"]
            )

        # 10. Daily Briefing triggers ("briefing", "fă-mi un briefing", "briefing matinal")
        briefing_phrases = [
            "briefing", "briefing matinal", "briefing zilnic", "fă-mi un briefing", "fa-mi un briefing",
            "rezumatul zilei", "sinteza de dimineață", "sinteza de dimineata", "start de zi", "startul zilei"
        ]
        if any(bp in prompt_clean for bp in briefing_phrases):
            return IntentDetectionResult(
                intent=IntentType.DAILY_BRIEFING,
                confidence=0.98,
                target_agents=["calendar_agent", "action_item_service", "news_agent"]
            )

        # 11. Multi-Tool Aggregated Overview (Section 6, Test T5: "Ce mai am de făcut?")
        overview_phrases = [
            "ce mai am de făcut", "ce mai am de facut",
            "ce am de făcut", "ce am de facut",
            "ce trebuie să fac", "ce trebuie sa fac",
            "ce mai trebuie să fac", "ce mai trebuie sa fac",
            "ce activități am", "ce activitati am",
            "ce e de făcut", "ce e de facut",
            "ce mai e de făcut", "ce mai e de facut",
            "ce am restant", "ce restanțe am", "ce restante am",
            "ce acțiuni am de făcut", "ce actiuni am de facut",
            "sinteză activități", "sinteza activitati",
            "toate sarcinile și evenimentele", "toate sarcinile si evenimentele"
        ]
        if any(op in prompt_clean for op in overview_phrases):
            return IntentDetectionResult(
                intent=IntentType.AGGREGATED_OVERVIEW,
                confidence=0.98,
                target_agents=["calendar_agent", "action_item_service", "email_agent", "practice_agent"]
            )

        # 12. Tasks / Action items queries
        task_list_keywords = [
            "ce sarcini am", "ce task-uri am", "ce taskuri am", "ce task uri am",
            "lista de sarcini", "lista de taskuri", "sarcinile mele", "taskurile mele",
            "ce actiuni am salvate", "ce acțiuni am salvate", "ce sarcini am de facut", "ce sarcini am de făcut",
            "ce taskuri am de facut", "ce task-uri am de facut", "sarcini salvate", "taskuri salvate"
        ]
        task_complete_keywords = [
            "marchează sarcina", "marcheaza sarcina", "bifează sarcina", "bifeaza sarcina",
            "finalizează sarcina", "finalizeaza sarcina", "rezolvă sarcina", "rezolva sarcina",
            "marchează task", "marcheaza task", "bifează task", "bifeaza task", "finalizat task"
        ]
        if any(kw in prompt_clean for kw in task_list_keywords) or any(kw in prompt_clean for kw in task_complete_keywords):
            return IntentDetectionResult(
                intent=IntentType.TASKS_QUERY,
                confidence=0.95,
                target_agents=["action_item_service"]
            )

        # 13. Calendar queries (schedule, events, agenda)
        calendar_keywords = [
            "calendar", "eveniment", "evenimente", "orar", "agenda",
            "consultatii", "consultații", "programare", "programări",
            "sedinta", "ședință", "sedinte", "ședințe", "intalnire", "întâlnire", "intalniri", "întâlniri"
        ]
        calendar_schedule_phrases = [
            "ce am azi", "ce am astazi", "ce am astăzi",
            "ce am mâine", "ce am maine", "ce am poimâine", "ce am poimaine",
            "ce am săptămâna", "ce am saptamana",
            "ce am programat",
            "ce fac azi", "ce fac mâine", "ce fac maine",
            "programul meu", "programul de azi", "programul de mâine", "programul de maine",
            "am ceva între", "am ceva intre", "sunt liber între", "sunt liber intre",
            "următorul eveniment", "urmatorul eveniment", "când este următorul", "cand este urmatorul",
            "următoarea ședință", "urmatoarea sedinta", "următoarea întâlnire", "urmatoarea intalnire",
            "și după al doilea", "si dupa al doilea", "după al doilea", "dupa al doilea",
            "cum arată săptămâna", "cum arata saptamana"
        ]
        if any(kw in prompt_clean for kw in calendar_keywords) or any(phrase in prompt_clean for phrase in calendar_schedule_phrases):
            return IntentDetectionResult(
                intent=IntentType.CALENDAR_QUERY,
                confidence=0.95,
                target_agents=["calendar_agent"]
            )

        # 9. Greetings
        if any(greet in prompt_clean for greet in ["salut", "buna", "bună", "hello", "hi"]):
            return IntentDetectionResult(
                intent=IntentType.GENERAL_GREETING,
                confidence=0.95,
                target_agents=[]
            )

        # Default
        return IntentDetectionResult(
            intent=IntentType.GENERAL_QUERY,
            confidence=0.7,
            target_agents=[]
        )

    async def process_request(
        self,
        user_prompt: str,
        user_id: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Main execution flow:
        User Prompt -> Intent Detection -> Agent Execution -> Response Text -> Audit Log
        """
        import time
        start_time = time.perf_counter()
        uid = require_user_id(user_id)
        logger.info("AIOrchestrator processing a Telegram request (length=%s).", len(user_prompt))
        
        intent_result = await self.detect_intent(user_prompt, user_id=uid, history=history)
        logger.info(f"Detected intent: {intent_result.intent.value} (confidence: {intent_result.confidence})")

        response_dict: Dict[str, Any] = {}
        # -------------------------------------------------------------
        # 1. PRACTICE DOCUMENT & RAG INTENTS EXECUTION
        # -------------------------------------------------------------
        if intent_result.intent == IntentType.PRACTICE_DOCUMENT_REQUEST:
            prompt_lower = user_prompt.lower()
            if "conventie_download" in prompt_lower:
                wants_convention = True
                wants_logbook = False
            elif "caiet_download" in prompt_lower:
                wants_convention = False
                wants_logbook = True
            elif "all_docs_download" in prompt_lower:
                wants_convention = True
                wants_logbook = True
            else:
                wants_convention = any(w in prompt_lower for w in ["conventi", "convenț", "conventie", "convenție"]) or any(w in prompt_lower for w in ["toate", "ambele", "documentele", "documente", "dosar"])
                wants_logbook = any(w in prompt_lower for w in ["caiet", "jurnal"]) or any(w in prompt_lower for w in ["toate", "ambele", "documentele", "documente", "dosar"])

            # If user said generic "generează documentele de practică", generate both
            if not wants_convention and not wants_logbook:
                wants_convention = True
                wants_logbook = True

            doc_items: List[Dict[str, Any]] = []
            deadlines_by_id = {d.get("id"): d for d in get_practice_deadlines()}
            conv_deadline = deadlines_by_id.get("conventie", {}).get("display_date", "28 August 2026")
            logbook_deadline = deadlines_by_id.get("caiet", {}).get("display_date", "2 Septembrie 2026")
            current_year = get_current_academic_year()

            if wants_convention:
                conv_bytes = self.document_generator_service.generate_convention_docx()
                doc_items.append({
                    "filename": "Conventie_Cadru_Practica_UNITBV.docx",
                    "bytes": conv_bytes,
                    "caption": f"📄 **Convenție-Cadru de Practică UNITBV** (Anul Universitar {current_year})"
                })
            if wants_logbook:
                log_bytes = self.document_generator_service.generate_logbook_docx()
                doc_items.append({
                    "filename": "Caiet_de_Practica_UNITBV.docx",
                    "bytes": log_bytes,
                    "caption": "📘 **Caiet de Practică & Jurnal de Activitate UNITBV** (90 ore)"
                })

            resp_lines = [
                "🎓 **Am generat documentele oficiale de practică conform cerințelor UNITBV FIESC:**\n"
            ]
            if wants_convention:
                resp_lines.append("• 📄 **Convenție-cadru de practică** (format Word .docx)")
                resp_lines.append("  - Se semnează în 3 exemplare originale (Student, Partener practică, Secretariat FIESC).")
                resp_lines.append(f"  - Termen limită depunere: **{conv_deadline}**.\n")
            if wants_logbook:
                resp_lines.append("• 📘 **Caiet de practică / Jurnal de activitate** (format Word .docx)")
                resp_lines.append("  - Structurat pe 3 săptămâni (90 de ore normate, 4 credite ECTS).")
                resp_lines.append("  - Include Fișa de evaluare și nota tutorelui companiei (50% din nota colocviului).")
                resp_lines.append(f"  - Termen limită încărcare dosar: **{logbook_deadline}**.\n")

            resp_lines.append("📎 Ți-am atașat documentele editabile direct în conversație pentru descărcare și completare.")
            response_dict = {
                "response": "\n".join(resp_lines),
                "intent": intent_result.intent.value,
                "target_agents": ["document_generator_service"],
                "documents": doc_items,
                "inline_keyboard": get_documents_download_keyboard()["inline_keyboard"],
                "model_used": "document_generator_service"
            }

        elif intent_result.intent == IntentType.PRACTICE_HISTORY_QUERY:
            result = await self.practice_agent.handle_historical_practice_query(
                user_prompt=user_prompt,
                user_id=uid,
            )
            response_dict = {
                "response": result["text"],
                "intent": intent_result.intent.value,
                "target_agents": ["practice_agent"],
                "model_used": settings.DEFAULT_MODEL
            }

        elif intent_result.intent == IntentType.PRACTICE_QUERY:
            result = await self.practice_agent.handle_practice_query(
                user_prompt=user_prompt,
                history=history,
                user_id=uid,
            )
            response_dict = {
                "response": result["text"],
                "intent": intent_result.intent.value,
                "target_agents": ["practice_agent"],
                "model_used": settings.DEFAULT_MODEL
            }

        # -------------------------------------------------------------
        # 2. CALENDAR INTENTS EXECUTION
        # -------------------------------------------------------------
        elif intent_result.intent == IntentType.CALENDAR_QUERY:
            result = await self.calendar_agent.handle_calendar_query(user_prompt=user_prompt, history=history)
            response_dict = {
                "response": result["text"],
                "intent": intent_result.intent.value,
                "target_agents": ["calendar_agent"],
                "model_used": settings.DEFAULT_MODEL
            }

        elif intent_result.intent == IntentType.CALENDAR_ADD_EVENT:
            result = await self.calendar_agent.handle_create_event_query(user_prompt=user_prompt)
            response_dict = {
                "response": result["text"],
                "intent": intent_result.intent.value,
                "target_agents": ["calendar_agent"],
                "model_used": settings.DEFAULT_MODEL
            }

        # -------------------------------------------------------------
        # 3. NEWS INTENTS EXECUTION
        # -------------------------------------------------------------
        elif intent_result.intent == IntentType.NEWS_QUERY:
            result = await self.news_agent.handle_news_query(user_prompt=user_prompt, user_id=uid)
            response_dict = {
                "response": result["text"],
                "intent": intent_result.intent.value,
                "target_agents": ["news_agent"],
                "model_used": settings.DEFAULT_MODEL
            }

        # -------------------------------------------------------------
        # 4. EMAIL INTENTS EXECUTION
        # -------------------------------------------------------------
        elif intent_result.intent == IntentType.EMAIL_SEND_CONFIRMATION:
            prompt_clean = user_prompt.strip(" .!?,;:\n").lower()
            prompt_raw = user_prompt.strip()

            if prompt_raw.startswith("approve_draft:"):
                pending_draft_id = prompt_raw.split(":", 1)[1].strip()
                approval_granted = True
            elif prompt_raw.startswith("reject_draft:"):
                pending_draft_id = prompt_raw.split(":", 1)[1].strip()
                approval_granted = False
            else:
                approval_granted = prompt_clean in ["da", "yes", "trimite", "da, trimite", "da trimite"]
                pending_draft_id = _user_pending_draft_map.get(uid)
                if not pending_draft_id:
                    draft = await self.email_agent.get_pending_draft_for_owner(uid)
                    pending_draft_id = draft.draft_id if draft else None

            if pending_draft_id:
                result = await self.email_agent.handle_approval(
                    draft_id=pending_draft_id,
                    approval_granted=approval_granted,
                    owner_id=uid,
                )
            else:
                result = {"text": "Nu există un draft în așteptare pentru acest utilizator.", "status": "error"}
            _user_pending_draft_map.pop(uid, None)

            response_dict = {
                "response": result["text"],
                "intent": intent_result.intent.value,
                "target_agents": ["email_agent"],
                "model_used": settings.DEFAULT_MODEL
            }

        elif intent_result.intent == IntentType.EMAIL_DRAFT_REPLY:
            prompt_raw = user_prompt.strip()
            target_msg_id = None
            user_prompt_for_draft = user_prompt
            if prompt_raw.startswith("reply_mail:"):
                mail_idx = prompt_raw.split(":", 1)[1].strip()
                user_prompt_for_draft = f"Răspunde la mailul {mail_idx}"
            elif prompt_raw.startswith("draft_reply:"):
                target_msg_id = prompt_raw.split(":", 1)[1].strip()
            result = await self.email_agent.handle_draft_reply(user_prompt=user_prompt_for_draft, message_id=target_msg_id, owner_id=uid)
            if result.get("draft_id"):
                _user_pending_draft_map[uid] = result["draft_id"]

            response_dict = {
                "response": result["text"],
                "intent": intent_result.intent.value,
                "target_agents": ["email_agent"],
                "draft_id": result.get("draft_id"),
                "model_used": settings.DEFAULT_MODEL
            }
            if result.get("draft_id"):
                response_dict["inline_keyboard"] = get_draft_approval_keyboard(result["draft_id"])["inline_keyboard"]

        elif intent_result.intent == IntentType.EMAIL_ACTION_ITEMS:
            result = await self.email_agent.handle_action_items_query(
                user_prompt=user_prompt,
                user_id=uid,
            )
            response_dict = {
                "response": result["text"],
                "intent": intent_result.intent.value,
                "target_agents": ["email_agent"],
                "model_used": settings.DEFAULT_MODEL
            }

        elif intent_result.intent in [IntentType.EMAIL_QUERY, IntentType.EMAIL_SEARCH, IntentType.EMAIL_SUMMARY]:
            is_important = "important" in user_prompt.lower()
            result = await self.email_agent.handle_email_query(
                user_prompt=user_prompt,
                is_important_only=is_important,
                user_id=uid,
            )
            response_dict = {
                "response": result["text"],
                "intent": intent_result.intent.value,
                "target_agents": ["email_agent"],
                "model_used": settings.DEFAULT_MODEL
            }
            if result.get("emails"):
                response_dict["inline_keyboard"] = get_email_action_keyboard(result["emails"])["inline_keyboard"]

        # -------------------------------------------------------------
        # 5. TASKS / ACTION ITEMS EXECUTION
        # -------------------------------------------------------------
        elif intent_result.intent == IntentType.TASKS_QUERY:
            import re
            prompt_lower = user_prompt.lower().strip()
            prompt_raw = user_prompt.strip()

            task_id = None
            if prompt_raw.startswith("complete_task:"):
                try:
                    task_id = int(prompt_raw.split(":", 1)[1].strip())
                except ValueError:
                    task_id = None
            else:
                complete_match = re.search(r'\b(?:task(?:ul)?|sarcina|sarcinii|nr\.?)\s*#?(\d+)\b', prompt_lower)
                is_complete_action = any(w in prompt_lower for w in ["marcheaza", "marchează", "bifeaza", "bifează", "finalizat", "rezolvat", "inchide", "închide", "gata"])
                if is_complete_action and complete_match:
                    task_id = int(complete_match.group(1))

            inline_kb = None
            if task_id is not None:
                success = await self.action_item_service.update_action_item_status(
                    item_id=task_id,
                    new_status="completed",
                    user_id=uid,
                )
                if success:
                    items = await self.action_item_service.list_action_items(status="open", user_id=uid)
                    if items:
                        lines = [
                            f"✅ **Sarcina #{task_id} a fost marcată ca finalizată!**\n",
                            f"📋 **Mai ai {len(items)} sarcini active în evidență**:\n"
                        ]
                        for idx, it in enumerate(items, 1):
                            lines.append(f"{idx}. [Task #{it['id']}] {it['title']}")
                        ans = "\n".join(lines)
                        inline_kb = get_tasks_action_keyboard(items)["inline_keyboard"]
                    else:
                        ans = f"✅ **Sarcina #{task_id} a fost marcată ca finalizată!**\n\n🎉 Felicitări! Toate sarcinile tale sunt finalizate la zi."
                else:
                    ans = f"⚠️ Nu am găsit sarcina **#{task_id}** în baza de date."
            else:
                items = await self.action_item_service.list_action_items(status="open", user_id=uid)
                if not items:
                    ans = "✅ Nu ai sarcini sau acțiuni deschise în acest moment. Toate activitățile tale sunt la zi!"
                else:
                    lines = [f"📋 **Sarcinile tale active ({len(items)} sarcini în așteptare)**:\n"]
                    for idx, it in enumerate(items, 1):
                        pri = it.get("priority", "medium").lower()
                        pri_emoji = "🔴" if pri == "high" else ("🟡" if pri == "medium" else "🟢")
                        deadline_val = it.get("deadline")
                        deadline_str = deadline_val.strftime("%d.%m.%Y %H:%M") if hasattr(deadline_val, "strftime") else (str(deadline_val) if deadline_val else "Nespecificat")

                        lines.append(f"{idx}. {pri_emoji} **[Task #{it['id']}]** {it['title']}")
                        lines.append(f"   • Prioritate: **{pri.upper()}**")
                        lines.append(f"   • Sursă: `{it.get('source', 'sistem')}`")
                        lines.append(f"   • Deadline: `{deadline_str}`")
                        lines.append("")
                    lines.append("💡 *Apasă pe oricare dintre butoanele de mai jos pentru a finaliza instant sarcina dorită.*")
                    ans = "\n".join(lines)
                    inline_kb = get_tasks_action_keyboard(items)["inline_keyboard"]

            response_dict = {
                "response": ans,
                "intent": intent_result.intent.value,
                "target_agents": ["action_item_service"],
                "model_used": "action_item_database"
            }
            if inline_kb:
                response_dict["inline_keyboard"] = inline_kb

        # -------------------------------------------------------------
        # 6. AGGREGATED MULTI-TOOL OVERVIEW (Section 6, Test T5: "Ce mai am de făcut?")
        # -------------------------------------------------------------
        elif intent_result.intent == IntentType.AGGREGATED_OVERVIEW:
            lines = ["📋 **Sinteza activităților tale – Ce ai de făcut:**\n"]

            # 1. Calendar upcoming events
            try:
                cal_res = await self.calendar_agent.handle_calendar_query("ce evenimente am în perioada următoare?")
                lines.append("📅 **Evenimente în Calendar**:")
                lines.append(cal_res.get("text", "Nu sunt evenimente programate."))
                lines.append("")
            except Exception as e:
                logger.debug(f"Aggregated overview calendar error: {e}")
                lines.append("📅 **Calendar**: Nu am putut prelua evenimentele în acest moment.")
                lines.append("")

            # 2. Open action items / tasks
            try:
                open_tasks = await self.action_item_service.list_action_items(status="open", user_id=uid)
                lines.append(f"📝 **Sarcini și Acțiuni Active ({len(open_tasks)} restante)**:")
                if open_tasks:
                    for idx, it in enumerate(open_tasks[:5], 1):
                        pri = it.get("priority", "medium").lower()
                        pri_emoji = "🔴" if pri == "high" else ("🟡" if pri == "medium" else "🟢")
                        deadline_val = it.get("deadline")
                        deadline_str = deadline_val.strftime("%d.%m.%Y %H:%M") if hasattr(deadline_val, "strftime") else (str(deadline_val) if deadline_val else "Fără deadline")
                        lines.append(f"{idx}. {pri_emoji} **[Task #{it['id']}]** {it['title']} (Deadline: `{deadline_str}`)")
                else:
                    lines.append("✅ Nicio sarcină restantă în baza de date! Ești la zi cu toate activitățile.")
                lines.append("")
            except Exception as e:
                logger.debug(f"Aggregated overview tasks error: {e}")

            # 3. Urgent emails requiring action
            try:
                action_emails = []
                for acc in ["personal", "unitbv"]:
                    try:
                        fetched = await self.email_agent.email_service.list_emails(
                            account_type=acc,
                            filter_params=EmailFilterParams(account_type=acc, limit=5),
                            user_id=uid,
                        )
                        for m in fetched:
                            if m.requires_action or m.is_practice_related or m.detected_deadline:
                                action_emails.append(m)
                    except Exception:
                        pass

                lines.append(f"📧 **E-mailuri ce necesită atenție ({len(action_emails)} identificate)**:")
                if action_emails:
                    for idx, em in enumerate(action_emails[:3], 1):
                        dl = f" | Deadline: `{em.detected_deadline}`" if em.detected_deadline else ""
                        lines.append(f"{idx}. ✉️ **{em.subject}** (De la: `{em.sender}`{dl})")
                else:
                    lines.append("✅ Nu ai e-mailuri urgente sau nesoluționate.")
                lines.append("")
            except Exception as e:
                logger.debug(f"Aggregated overview emails error: {e}")

            # 4. Practice Milestones & Deadlines (UNITBV FIESC)
            current_year = get_current_academic_year()
            lines.append(f"🎓 **Termene Limită Practică UNITBV (Anul {current_year})**:")
            icon_map = {"conventie": "📄", "caiet": "📘", "colocviu": "🎯"}
            for dl in get_practice_deadlines():
                ic = icon_map.get(dl.get("id"), "📌")
                lines.append(f"• {ic} **{dl.get('display_date')}**: {dl.get('description')}")
            lines.append("")
            lines.append("💡 *Apasă pe butoanele de mai jos pentru a gestiona direct sarcinile sau a descărca documentele necesare.*")

            overview_keyboard = [
                [{"text": "📋 Sarcinile Mele", "callback_data": "/sarcini"}, {"text": "📅 Calendar", "callback_data": "/calendar"}],
                [{"text": "📧 Verifică Emailuri", "callback_data": "/email"}, {"text": "📄 Convenție (.docx)", "callback_data": "conventie_download"}]
            ]

            response_dict = {
                "response": "\n".join(lines),
                "intent": intent_result.intent.value,
                "target_agents": ["calendar_agent", "action_item_service", "email_agent", "practice_agent"],
                "inline_keyboard": overview_keyboard,
                "model_used": "multi_agent_orchestrator"
            }

        # -------------------------------------------------------------
        # 7. DAILY MORNING BRIEFING
        # -------------------------------------------------------------
        elif intent_result.intent == IntentType.DAILY_BRIEFING:
            from datetime import datetime
            today_str = datetime.now().strftime("%d.%m.%Y")
            briefing_lines = [
                f"🌅 **Sinteza ta zilnică academică ({today_str})**:\n"
            ]

            # Calendar
            try:
                cal_res = await self.calendar_agent.handle_calendar_query("ce am azi?")
                briefing_lines.append("📅 **Programul tău de astăzi**:")
                briefing_lines.append(cal_res.get("text", "Niciun eveniment programat pentru astăzi."))
                briefing_lines.append("")
            except Exception as e:
                logger.debug(f"Daily briefing calendar check error: {e}")

            # Email Status (Section 17: EMAIL)
            try:
                all_emails = []
                for acc in ["personal", "unitbv"]:
                    try:
                        fetched = await self.email_agent.email_service.list_emails(
                            account_type=acc,
                            filter_params=EmailFilterParams(limit=5),
                            user_id=uid,
                        )
                        all_emails.extend(fetched)
                    except Exception:
                        pass
                important_count = sum(1 for e in all_emails if e.importance in ["high", "important"] or e.is_practice_related)
                action_count = sum(1 for e in all_emails if e.requires_action or e.detected_deadline)
                briefing_lines.append("📧 **E-mailuri Noi & Necesitate Răspuns**:")
                if all_emails:
                    briefing_lines.append(f"• {len(all_emails)} mesaje verificate ({important_count} importante)")
                    if action_count > 0:
                        briefing_lines.append(f"• ⚠️ {action_count} mesaje necesită răspuns sau acțiune")
                    else:
                        briefing_lines.append("• ✅ Niciun mesaj nu necesită răspuns urgent")
                else:
                    briefing_lines.append("• Căsuțele poștale sunt la zi (niciun mesaj nou)")
                briefing_lines.append("")
            except Exception as e:
                logger.debug(f"Daily briefing email check error: {e}")

            # UNITBV / Practică Status (Section 17: UNITBV / PRACTICĂ)
            briefing_lines.append("🎓 **UNITBV / Practică Studențească**:")
            for dl in get_practice_deadlines()[:2]:
                briefing_lines.append(f"• Termen limită {dl.get('title', '')}: **{dl.get('display_date', '')}**")
            briefing_lines.append("")

            # Open Tasks (Section 17: ACTION ITEMS)
            try:
                items = await self.action_item_service.list_action_items(status="open", user_id=uid)
                if items:
                    briefing_lines.append(f"📋 **Sarcini prioritare ({len(items)} în așteptare)**:")
                    for idx, it in enumerate(items[:3], 1):
                        pri = it.get("priority", "medium").upper()
                        briefing_lines.append(f"{idx}. [Task #{it['id']}] {it['title']} ({pri})")
                    briefing_lines.append("")
                else:
                    briefing_lines.append("📋 **Sarcini**: Nicio sarcină restantă! Ești la zi.")
                    briefing_lines.append("")
            except Exception as e:
                logger.debug(f"Daily briefing tasks check error: {e}")

            # Tech News
            try:
                articles = await NewsService().fetch_and_process_news(max_results=2, user_id=uid)
                if articles:
                    briefing_lines.append("📰 **Top Știri Tehnologice Relevante**:")
                    for n in articles[:2]:
                        briefing_lines.append(f"• [{n.title}]({n.url})")
                    briefing_lines.append("")
            except Exception as e:
                logger.debug(f"Daily briefing news check error: {e}")

            briefing_lines.append("🚀 O zi plină de spor și productivitate la Universitatea Transilvania!")

            briefing_keyboard = [
                [{"text": "📅 Deschide Calendar", "callback_data": "/calendar"}, {"text": "📋 Sarcinile Mele", "callback_data": "/sarcini"}],
                [{"text": "📧 Verifică Emailuri", "callback_data": "/email"}, {"text": "📰 Știri Tehnologice", "callback_data": "/stiri"}]
            ]

            response_dict = {
                "response": "\n".join(briefing_lines),
                "intent": intent_result.intent.value,
                "target_agents": ["calendar_agent", "action_item_service", "news_agent"],
                "inline_keyboard": briefing_keyboard,
                "model_used": "multi_agent_orchestrator"
            }

        # -------------------------------------------------------------
        # 8. LONG-TERM USER MEMORY & PREFERENCES MANAGEMENT
        # -------------------------------------------------------------
        elif intent_result.intent == IntentType.MEMORY_MANAGE:
            prompt_clean = user_prompt.strip().lower()
            # A. Clear / Reset Memory
            if any(w in prompt_clean for w in ["șterge memoria", "sterge memoria", "uită tot", "uita tot", "resetează", "reseteaza", "șterge preferințele", "sterge preferintele"]):
                existing = await self.user_memory_service.list_memories(user_id=uid)
                count = 0
                for it in existing:
                    if await self.user_memory_service.delete_memory(it["key"], user_id=uid):
                        count += 1
                ans = f"🧹 **Memoria pe termen lung a fost resetată.** Am șters {count} preferințe și reguli memorate anterior."
            # B. Query / List Memories
            elif any(w in prompt_clean for w in ["ce preferințe", "ce preferinte", "ce reguli", "ce ții minte", "ce tii minte", "ce memorie", "ce ai memorat", "/memorie", "/preferinte", "/reguli"]):
                memories = await self.user_memory_service.list_memories(user_id=uid)
                if not memories:
                    ans = (
                        "🧠 **Nu ai preferințe sau reguli salvate în memoria pe termen lung.**\n\n"
                        "Poți seta reguli oricând spunându-mi de exemplu:\n"
                        "• *„Ține minte că prefer răspunsurile concise și la obiect.”*\n"
                        "• *„Prefer să nu am ședințe programate înainte de ora 10:00.”*\n"
                        "• *„Ține minte că adresa mea de e-mail instituțional este prenume.nume@student.unitbv.ro.”*"
                    )
                else:
                    lines = ["🧠 **Preferințe și Reguli Personale Memorate**:\n"]
                    for idx, m in enumerate(memories, 1):
                        lines.append(f"{idx}. 📌 `{m['key']}`: *{m['value']}*")
                    lines.append("\n💡 *Toate aceste reguli sunt aplicate automat de către asistent în fiecare conversație.*")
                    ans = "\n".join(lines)
            # C. Store New Memory
            else:
                raw = user_prompt.strip()
                cleaned_val = raw
                for trigger in [
                    "salvează preferința că", "salveaza preferinta ca",
                    "salvează preferința", "salveaza preferinta",
                    "salvează regula că", "salveaza regula ca",
                    "salvează regula", "salveaza regula",
                    "ține minte că", "tine minte ca", "ține minte ca", "tine minte că",
                    "reține că", "retine ca", "reține regula", "retine regula",
                    "memorează că", "memoreaza ca"
                ]:
                    if cleaned_val.lower().startswith(trigger):
                        cleaned_val = cleaned_val[len(trigger):].strip(" ,:;\n")
                        break

                import re
                import time
                key_candidate = re.sub(r'[^a-zA-Z0-9_]', '_', cleaned_val[:24].strip().lower()).strip('_')
                if not key_candidate:
                    key_candidate = f"rule_{int(time.time())}"
                else:
                    key_candidate = f"pref_{key_candidate}"

                await self.user_memory_service.set_memory(
                    key=key_candidate,
                    value=cleaned_val,
                    category="preference",
                    user_id=uid,
                )
                ans = (
                    f"🧠 **Am salvat noua regulă în memoria pe termen lung!**\n\n"
                    f"📌 **Regulă salvată**: *„{cleaned_val}”*\n"
                    f"🔑 **Cheie identificator**: `{key_candidate}`\n\n"
                    f"✅ Voi ține cont de această preferință în toate răspunsurile și acțiunile viitoare."
                )

            response_dict = {
                "response": ans,
                "intent": intent_result.intent.value,
                "target_agents": ["user_memory_service"],
                "model_used": "user_memory_service"
            }

        # -------------------------------------------------------------
        # 9. GENERAL / GREETING SYNTHESIS VIA LLMPROVIDER
        # -------------------------------------------------------------
        else:
            from datetime import datetime
            now = datetime.now()
            ro_days = ["luni", "marți", "miercuri", "joi", "vineri", "sâmbătă", "duminică"]
            ro_months = [
                "ianuarie", "februarie", "martie", "aprilie", "mai", "iunie",
                "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie"
            ]
            day_name = ro_days[now.weekday()]
            month_name = ro_months[now.month - 1]
            current_date_str = f"{day_name.capitalize()}, {now.day} {month_name} {now.year}"
            current_time_str = now.strftime("%H:%M")

            prompt_clean = user_prompt.strip(" .!?,;:\n").lower()
            date_questions = [
                "ce zi este", "ce zi e", "in ce zi suntem", "în ce zi suntem",
                "ce data este", "ce data e", "ce dată este", "ce dată e",
                "ce data avem", "ce dată avem", "data de azi", "data de astăzi"
            ]
            time_questions = [
                "cat e ceasul", "cât e ceasul", "ce ora e", "ce oră e", "ce ora este", "ce oră este"
            ]

            countdown_keywords = [
                "cate zile mai sunt", "câte zile mai sunt", "cat mai este pana",
                "cât mai este până", "cat mai e pana", "cât mai e până", "cate zile pana", "câte zile până"
            ]

            if any(dq in prompt_clean for dq in date_questions):
                response_dict = {
                    "response": f"📅 Astăzi este **{current_date_str}**.",
                    "intent": intent_result.intent.value,
                    "target_agents": [],
                    "model_used": "system_clock"
                }
            elif any(tq in prompt_clean for tq in time_questions):
                response_dict = {
                    "response": f"⏰ Este ora **{current_time_str}**.",
                    "intent": intent_result.intent.value,
                    "target_agents": [],
                    "model_used": "system_clock"
                }
            elif any(wk in prompt_clean for wk in [
                "vremea", "meteo", "temperatura", "temperatură",
                "ploua", "plouă", "ninge", "date meteorologice", "datele meteorologice",
                "prognoza", "prognoză", "prognoza meteo", "prognoză meteo"
            ]):
                weather_info = await self._fetch_live_weather(user_prompt)
                response_dict = {
                    "response": weather_info,
                    "intent": intent_result.intent.value,
                    "target_agents": [],
                    "model_used": "open_meteo"
                }
            elif any(ck in prompt_clean for ck in countdown_keywords):
                if any(ak in prompt_clean for ak in ["an universitar", "anul universitar", "inceperea noului an", "începerea noului an", "facultate", "inceputul anului", "începutul anului", "1 octombrie"]):
                    target_year = now.year if now.month < 10 else now.year + 1
                    target_date = datetime(target_year, 10, 1).date()
                    days_left = (target_date - now.date()).days
                    acad_year = get_current_academic_year()
                    if days_left > 0:
                        ans = f"🎓 Mai sunt exact **{days_left} de zile** până la deschiderea noului an universitar {acad_year} (1 octombrie {target_year})."
                    elif days_left == 0:
                        ans = f"🎓 Noul an universitar {acad_year} începe chiar astăzi, 1 octombrie!"
                    else:
                        ans = f"🎓 Noul an universitar {acad_year} a început deja."
                    response_dict = {
                        "response": ans,
                        "intent": intent_result.intent.value,
                        "target_agents": [],
                        "model_used": "system_clock"
                    }
                else:
                    system_prompt = (
                        f"Ești Personal Academic AI Assistant pentru un student / cadru didactic la Universitatea Transilvania din Brașov (UNITBV).\n"
                        f"Data și ora curentă: {current_date_str}, {current_time_str}.\n"
                        f"Anul universitar curent este: {settings.CURRENT_ACADEMIC_YEAR}.\n"
                        f"Calculează cu atenție numărul de zile rămas până la evenimentul cerut.\n"
                        f"Răspunde amabil, concis și structurat în limba română."
                    )
                    completion_result = await self.llm.generate_completion(
                        prompt=user_prompt,
                        system_prompt=system_prompt,
                        history=history,
                        temperature=0.3
                    )
                    response_dict = {
                        "response": completion_result.get("content", "Am procesat solicitarea ta."),
                        "intent": intent_result.intent.value,
                        "target_agents": intent_result.target_agents,
                        "model_used": getattr(self.llm, "model", settings.DEFAULT_MODEL)
                    }
            else:
                memories = []
                try:
                    memories = await self.user_memory_service.list_memories(user_id=uid)
                except Exception as mem_e:
                    logger.debug("User memories load error: %s", mem_e)

                memory_prompt_part = ""
                if memories:
                    mem_rules = "\n".join([f"• {m['value']}" for m in memories])
                    memory_prompt_part = (
                        f"\n\nPreferințe și reguli personale memorate de la utilizator (trebuie respectate cu prioritate):\n"
                        f"{mem_rules}"
                    )

                system_prompt = (
                    f"Ești Personal Academic AI Assistant pentru un student / cadru didactic la Universitatea Transilvania din Brașov (UNITBV).\n"
                    f"Data și ora curentă: {current_date_str}, {current_time_str}.\n"
                    f"Anul universitar curent este: {settings.CURRENT_ACADEMIC_YEAR}.\n"
                    f"Răspunde amabil, concis și structurat în limba română."
                    f"{memory_prompt_part}"
                )

                completion_result = await self.llm.generate_completion(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    history=history,
                    temperature=0.7
                )

                response_dict = {
                    "response": completion_result.get("content", "Am procesat solicitarea ta."),
                    "intent": intent_result.intent.value,
                    "target_agents": intent_result.target_agents,
                    "model_used": getattr(self.llm, "model", settings.DEFAULT_MODEL)
                }

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        try:
            await self.audit_service.log_event(
                user_id=uid,
                user_request=user_prompt,
                selected_tool=intent_result.intent.value,
                model_used=response_dict.get("model_used"),
                status="success",
                execution_duration_ms=round(duration_ms, 2),
                external_operation="process_request",
            )
        except Exception as exc:
            logger.debug(f"Audit log error: {exc}")

        return response_dict

    @staticmethod
    async def _fetch_live_weather(query: str) -> str:
        """
        Fetches live real-time weather information using Open-Meteo API.
        Dynamically extracts and geocodes any city (e.g. Buzău, Cluj, etc.),
        defaulting to Brașov (UNITBV) if no specific location is mentioned.
        """
        import re
        import httpx
        city = "Brașov"
        lat, lon = 45.658, 25.601

        m = re.search(r'\b(?:în|in|la|din)\s+([a-zăâîșțA-ZĂÂÎȘȚ\-]+)', query, re.IGNORECASE)
        target_name = m.group(1) if m else None
        if target_name and target_name.lower() not in ["afara", "afară", "prezent", "general", "timp", "casa", "casă"]:
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    geo = await client.get(f"https://geocoding-api.open-meteo.com/v1/search?name={target_name}&count=1")
                    if geo.status_code == 200 and geo.json().get("results"):
                        res0 = geo.json()["results"][0]
                        city, lat, lon = res0["name"], res0["latitude"], res0["longitude"]
            except Exception:
                pass

        wmo_map = {
            0: "Cer senin ☀️",
            1: "Predominant senin 🌤️",
            2: "Parțial înnorat ⛅",
            3: "Înnorat ☁️",
            45: "Ceață 🌫️",
            48: "Ceață densă 🌫️",
            51: "Burniță ușoară 🌦️",
            61: "Ploaie slabă 🌧️",
            63: "Ploaie moderată 🌧️",
            65: "Ploaie torențială 🌧️",
            71: "Ninsoare slabă 🌨️",
            73: "Ninsoare ❄️",
            80: "Averse de ploaie 🌦️",
            95: "Furtună cu descărcări electrice ⛈️"
        }

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.get(
                    f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
                )
                if res.status_code == 200:
                    cw = res.json().get("current_weather", {})
                    temp = cw.get("temperature", "N/A")
                    wind = cw.get("windspeed", "N/A")
                    code = cw.get("weathercode", 0)
                    desc = wmo_map.get(code, "Variabil 🌤️")
                    return (
                        f"🌤️ **Date meteorologice în timp real ({city})**:\n\n"
                        f"• Starea vremii: **{desc}**\n"
                        f"• Temperatură: **{temp}°C**\n"
                        f"• Viteza vântului: **{wind} km/h**\n"
                        f"• Sursă: Serviciul meteorologic Open-Meteo"
                    )
        except Exception as exc:
            logger.warning("Weather fetch failed: %s", exc)
        return "Nu am putut prelua datele meteorologice în timp real momentan. Te rog încearcă din nou puțin mai târziu."
