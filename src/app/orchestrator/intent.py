from enum import Enum
from typing import List, Optional
from pydantic import BaseModel


class IntentType(str, Enum):
    GENERAL_GREETING = "general_greeting"
    GENERAL_QUERY = "general_query"
    CALENDAR_QUERY = "calendar_query"
    CALENDAR_ADD_EVENT = "calendar_add_event"
    CALENDAR_UPDATE_EVENT = "calendar_update_event"
    CALENDAR_DELETE_EVENT = "calendar_delete_event"
    CALENDAR_CONFIRM_ACTION = "calendar_confirm_action"
    CALENDAR_CANCEL_ACTION = "calendar_cancel_action"
    
    # Email Intents (M2)
    EMAIL_QUERY = "email_query"
    EMAIL_SEARCH = "email_search"
    EMAIL_SUMMARY = "email_summary"
    EMAIL_CLASSIFICATION = "email_classification"
    EMAIL_ACTION_ITEMS = "email_action_items"
    EMAIL_DRAFT_REPLY = "email_draft_reply"
    EMAIL_SEND_CONFIRMATION = "email_send_confirmation"

    PRACTICE_QUERY = "practice_query"
    PRACTICE_HISTORY_QUERY = "practice_history_query"
    PRACTICE_DOCUMENT_REQUEST = "practice_document_request"
    NEWS_QUERY = "news_query"
    TASKS_QUERY = "tasks_query"

    # Multi-Tool Synthesis & Long-Term Memory
    MEMORY_MANAGE = "memory_manage"
    AGGREGATED_OVERVIEW = "aggregated_overview"
    DAILY_BRIEFING = "daily_briefing"


class IntentDetectionResult(BaseModel):
    intent: IntentType
    confidence: float
    detected_keywords: List[str] = []
    target_agents: List[str] = []
    summary: Optional[str] = None
