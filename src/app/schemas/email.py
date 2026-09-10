from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class EmailFilterParams(BaseModel):
    account_type: str = "personal"  # "personal" or "unitbv"
    days_back: Optional[int] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    sender: Optional[str] = None
    subject: Optional[str] = None
    keywords: Optional[List[str]] = None
    is_important_only: bool = False
    limit: int = 10


class EmailActionItem(BaseModel):
    action: str
    deadline: Optional[str] = None
    priority: str = "medium"


class EmailClassificationResult(BaseModel):
    category: str  # "important", "academic", "practice", "action_required", "personal", "informational"
    importance: str  # "high", "medium", "low"
    reason: str
    requires_action: bool = False
    detected_deadline: Optional[str] = None
    actions: List[EmailActionItem] = Field(default_factory=list)


class EmailMessageSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    message_id: str
    account_type: str  # "personal" or "unitbv"
    sender: str
    recipients: List[str] = Field(default_factory=list)
    subject: str
    body_text: str
    received_at: datetime
    summary: Optional[str] = None
    category: Optional[str] = None
    importance: Optional[str] = "medium"
    is_practice_related: bool = False
    requires_action: bool = False
    detected_deadline: Optional[str] = None
    actions: List[EmailActionItem] = Field(default_factory=list)


class EmailDraftReply(BaseModel):
    draft_id: str
    original_message_id: str
    account_type: str
    recipient: str
    subject: str
    body: str
    status: str = "pending_approval"  # "pending_approval", "approved", "rejected", "sent"
    metadata: Dict[str, Any] = Field(default_factory=dict)
    owner_id: Optional[str] = None
    expires_at: Optional[datetime] = None
