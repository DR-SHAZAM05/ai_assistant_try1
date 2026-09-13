from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Float, JSON, Enum,
    UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime
import enum

Base = declarative_base()


class PriorityEnum(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ActionStatusEnum(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_chat_id = Column(String(64), unique=True, index=True, nullable=True)
    full_name = Column(String(128), nullable=False)
    preferred_language = Column(String(10), default="ro")
    created_at = Column(DateTime, default=datetime.utcnow)


class AcademicYear(Base):
    __tablename__ = "academic_years"

    id = Column(Integer, primary_key=True, index=True)
    year_code = Column(String(32), unique=True, index=True, nullable=False) # e.g. "2025-2026"
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class EmailAccount(Base):
    __tablename__ = "email_accounts"

    id = Column(Integer, primary_key=True, index=True)
    account_type = Column(String(32), nullable=False) # "personal" or "unitbv"
    email_address = Column(String(128), unique=True, nullable=False)
    is_active = Column(Boolean, default=True)


class Email(Base):
    __tablename__ = "emails"
    __table_args__ = (
        UniqueConstraint("user_id", "account_type", "message_id", name="uq_emails_user_account_message"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), index=True, nullable=False)
    message_id = Column(String(256), index=True, nullable=False)
    account_type = Column(String(32), nullable=False)
    sender = Column(String(256), nullable=False)
    recipients = Column(JSON, nullable=True)
    subject = Column(String(512), nullable=True)
    body_text = Column(Text, nullable=True)
    received_at = Column(DateTime, nullable=False)
    summary = Column(Text, nullable=True)
    category = Column(String(64), nullable=True)
    importance = Column(String(32), nullable=True)
    is_practice_related = Column(Boolean, default=False)
    requires_action = Column(Boolean, default=False)
    detected_deadline = Column(DateTime, nullable=True)
    actions = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PendingEmailDraft(Base):
    __tablename__ = "pending_email_drafts"

    id = Column(Integer, primary_key=True, index=True)
    draft_id = Column(String(64), unique=True, index=True, nullable=False)
    owner_id = Column(String(64), index=True, nullable=False)
    original_message_id = Column(String(256), nullable=False)
    account_type = Column(String(32), nullable=False)
    recipient = Column(String(512), nullable=False)
    subject = Column(String(512), nullable=False)
    body = Column(Text, nullable=False)
    draft_metadata = Column("metadata", JSON, nullable=True)
    status = Column(String(32), index=True, nullable=False, default="pending_approval")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    decided_at = Column(DateTime, nullable=True)


class PracticeQuestion(Base):
    __tablename__ = "practice_questions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), index=True, nullable=False)
    academic_year = Column(String(32), index=True, nullable=False)
    student_name = Column(String(128), nullable=True)
    student_group = Column(String(32), nullable=True)
    topic = Column(String(128), nullable=False)
    question_summary = Column(Text, nullable=False)
    source_type = Column(String(64), nullable=False) # e.g. "unitbv_email", "telegram"
    source_reference = Column(String(256), nullable=True)
    tags = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    answers = relationship("PracticeAnswer", back_populates="question", cascade="all, delete-orphan")


class PracticeAnswer(Base):
    __tablename__ = "practice_answers"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), index=True, nullable=False)
    question_id = Column(Integer, ForeignKey("practice_questions.id", ondelete="CASCADE"), nullable=False)
    answer_summary = Column(Text, nullable=False)
    decision = Column(String(128), nullable=True)
    academic_year = Column(String(32), index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    question = relationship("PracticeQuestion", back_populates="answers")


class PracticeDocument(Base):
    __tablename__ = "practice_documents"
    __table_args__ = (
        UniqueConstraint("academic_year", "file_path", "qdrant_collection", name="uq_practice_document_year_path_collection"),
    )

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(String(256), index=True, nullable=False)
    academic_year = Column(String(32), index=True, nullable=False)
    file_name = Column(String(256), nullable=False)
    file_path = Column(String(512), nullable=False)
    document_type = Column(String(64), nullable=False) # e.g. "rules", "template"
    qdrant_collection = Column(String(128), nullable=False)
    checksum = Column(String(64), index=True, nullable=False)
    status = Column(String(32), index=True, default="processed", nullable=False)
    chunks_count = Column(Integer, default=0, nullable=False)
    vectors_count = Column(Integer, default=0, nullable=False)
    document_metadata = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ActionItem(Base):
    __tablename__ = "action_items"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), index=True, nullable=False)
    title = Column(String(256), nullable=False)
    source = Column(String(64), nullable=False) # "email", "calendar", "practice"
    deadline = Column(DateTime, nullable=True)
    priority = Column(Enum(PriorityEnum, values_callable=lambda x: [e.value for e in x], name="priorityenum"), default=PriorityEnum.MEDIUM)
    status = Column(Enum(ActionStatusEnum, values_callable=lambda x: [e.value for e in x], name="actionstatusenum"), default=ActionStatusEnum.OPEN)
    source_reference = Column(String(256), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("user_id", "session_id", name="uq_conversations_user_session"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), index=True, nullable=False)
    telegram_chat_id = Column(String(64), index=True, nullable=False)
    session_id = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    messages = relationship("ConversationMessage", back_populates="conversation", cascade="all, delete-orphan")


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    sender_role = Column(String(32), nullable=False) # "user", "assistant", "system"
    content = Column(Text, nullable=False)
    tool_calls = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")


class UserMemory(Base):
    __tablename__ = "user_memories"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_user_memory_user_key"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), index=True, nullable=False)
    key = Column(String(128), index=True, nullable=False)
    value = Column(Text, nullable=False)
    category = Column(String(64), nullable=True) # e.g. "preference", "rule"
    created_at = Column(DateTime, default=datetime.utcnow)


class NewsArticle(Base):
    __tablename__ = "news_articles"
    __table_args__ = (
        UniqueConstraint("user_id", "url", name="uq_news_article_user_url"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), index=True, nullable=False)
    title = Column(String(512), nullable=False)
    url = Column(String(1024), nullable=False)
    source_name = Column(String(256), nullable=False, default="RSS")
    fingerprint = Column(String(64), index=True, nullable=True)
    topic = Column(String(64), nullable=False)
    relevance_score = Column(Float, default=0.0)
    content = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), index=True, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    user_request = Column(Text, nullable=True)
    selected_tool = Column(String(128), nullable=True)
    model_used = Column(String(64), nullable=True)
    status = Column(String(32), nullable=False) # "success" or "error"
    execution_duration_ms = Column(Float, nullable=True)
    external_operation = Column(String(256), nullable=True)
    rag_sources = Column(JSON, nullable=True)
