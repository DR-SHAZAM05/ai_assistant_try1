INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Generating static SQL
INFO  [alembic.runtime.migration] Will assume transactional DDL.
BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

INFO  [alembic.runtime.migration] Running upgrade  -> 001_initial_m2_tables, Create the relational schema used by the academic assistant.
-- Running upgrade  -> 001_initial_m2_tables

CREATE TABLE users (
    id SERIAL NOT NULL, 
    telegram_chat_id VARCHAR(64), 
    full_name VARCHAR(128) NOT NULL, 
    preferred_language VARCHAR(10) DEFAULT 'ro', 
    created_at TIMESTAMP WITHOUT TIME ZONE, 
    PRIMARY KEY (id), 
    UNIQUE (telegram_chat_id)
);

CREATE INDEX ix_users_id ON users (id);

CREATE INDEX ix_users_telegram_chat_id ON users (telegram_chat_id);

CREATE TABLE academic_years (
    id SERIAL NOT NULL, 
    year_code VARCHAR(32) NOT NULL, 
    is_active BOOLEAN DEFAULT false, 
    created_at TIMESTAMP WITHOUT TIME ZONE, 
    PRIMARY KEY (id), 
    UNIQUE (year_code)
);

CREATE INDEX ix_academic_years_id ON academic_years (id);

CREATE INDEX ix_academic_years_year_code ON academic_years (year_code);

CREATE TABLE email_accounts (
    id SERIAL NOT NULL, 
    account_type VARCHAR(32) NOT NULL, 
    email_address VARCHAR(128) NOT NULL, 
    is_active BOOLEAN DEFAULT true, 
    PRIMARY KEY (id), 
    UNIQUE (email_address)
);

CREATE INDEX ix_email_accounts_id ON email_accounts (id);

CREATE TABLE emails (
    id SERIAL NOT NULL, 
    message_id VARCHAR(256) NOT NULL, 
    account_type VARCHAR(32) NOT NULL, 
    sender VARCHAR(256) NOT NULL, 
    subject VARCHAR(512), 
    body_text TEXT, 
    received_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
    summary TEXT, 
    category VARCHAR(64), 
    is_practice_related BOOLEAN DEFAULT false, 
    requires_action BOOLEAN DEFAULT false, 
    detected_deadline TIMESTAMP WITHOUT TIME ZONE, 
    created_at TIMESTAMP WITHOUT TIME ZONE, 
    PRIMARY KEY (id), 
    UNIQUE (message_id)
);

CREATE INDEX ix_emails_id ON emails (id);

CREATE INDEX ix_emails_message_id ON emails (message_id);

CREATE TABLE practice_questions (
    id SERIAL NOT NULL, 
    academic_year VARCHAR(32) NOT NULL, 
    student_name VARCHAR(128), 
    student_group VARCHAR(32), 
    topic VARCHAR(128) NOT NULL, 
    question_summary TEXT NOT NULL, 
    source_type VARCHAR(64) NOT NULL, 
    source_reference VARCHAR(256), 
    tags JSON, 
    created_at TIMESTAMP WITHOUT TIME ZONE, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_practice_questions_id ON practice_questions (id);

CREATE INDEX ix_practice_questions_academic_year ON practice_questions (academic_year);

CREATE TABLE practice_answers (
    id SERIAL NOT NULL, 
    question_id INTEGER NOT NULL, 
    answer_summary TEXT NOT NULL, 
    decision VARCHAR(128), 
    academic_year VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITHOUT TIME ZONE, 
    PRIMARY KEY (id), 
    FOREIGN KEY(question_id) REFERENCES practice_questions (id) ON DELETE CASCADE
);

CREATE INDEX ix_practice_answers_id ON practice_answers (id);

CREATE INDEX ix_practice_answers_academic_year ON practice_answers (academic_year);

CREATE TYPE priorityenum AS ENUM ('low', 'medium', 'high');

CREATE TYPE actionstatusenum AS ENUM ('open', 'in_progress', 'completed', 'cancelled');

CREATE TABLE action_items (
    id SERIAL NOT NULL, 
    title VARCHAR(256) NOT NULL, 
    source VARCHAR(64) NOT NULL, 
    deadline TIMESTAMP WITHOUT TIME ZONE, 
    priority priorityenum DEFAULT 'medium', 
    status actionstatusenum DEFAULT 'open', 
    source_reference VARCHAR(256), 
    created_at TIMESTAMP WITHOUT TIME ZONE, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_action_items_id ON action_items (id);

CREATE TABLE conversations (
    id SERIAL NOT NULL, 
    telegram_chat_id VARCHAR(64) NOT NULL, 
    session_id VARCHAR(64) NOT NULL, 
    created_at TIMESTAMP WITHOUT TIME ZONE, 
    PRIMARY KEY (id), 
    UNIQUE (session_id)
);

CREATE INDEX ix_conversations_id ON conversations (id);

CREATE INDEX ix_conversations_telegram_chat_id ON conversations (telegram_chat_id);

CREATE TABLE conversation_messages (
    id SERIAL NOT NULL, 
    conversation_id INTEGER NOT NULL, 
    sender_role VARCHAR(32) NOT NULL, 
    content TEXT NOT NULL, 
    tool_calls JSON, 
    created_at TIMESTAMP WITHOUT TIME ZONE, 
    PRIMARY KEY (id), 
    FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
);

CREATE INDEX ix_conversation_messages_id ON conversation_messages (id);

CREATE TABLE user_memories (
    id SERIAL NOT NULL, 
    key VARCHAR(128) NOT NULL, 
    value TEXT NOT NULL, 
    category VARCHAR(64), 
    created_at TIMESTAMP WITHOUT TIME ZONE, 
    PRIMARY KEY (id), 
    UNIQUE (key)
);

CREATE INDEX ix_user_memories_id ON user_memories (id);

CREATE INDEX ix_user_memories_key ON user_memories (key);

CREATE TABLE news_articles (
    id SERIAL NOT NULL, 
    title VARCHAR(512) NOT NULL, 
    url VARCHAR(1024) NOT NULL, 
    topic VARCHAR(64) NOT NULL, 
    relevance_score FLOAT DEFAULT '0', 
    summary TEXT, 
    published_at TIMESTAMP WITHOUT TIME ZONE, 
    created_at TIMESTAMP WITHOUT TIME ZONE, 
    PRIMARY KEY (id), 
    UNIQUE (url)
);

CREATE INDEX ix_news_articles_id ON news_articles (id);

CREATE TABLE audit_logs (
    id SERIAL NOT NULL, 
    timestamp TIMESTAMP WITHOUT TIME ZONE, 
    user_request TEXT, 
    selected_tool VARCHAR(128), 
    model_used VARCHAR(64), 
    status VARCHAR(32) NOT NULL, 
    execution_duration_ms FLOAT, 
    external_operation VARCHAR(256), 
    rag_sources JSON, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_audit_logs_id ON audit_logs (id);

INSERT INTO alembic_version (version_num) VALUES ('001_initial_m2_tables') RETURNING alembic_version.version_num;

INFO  [alembic.runtime.migration] Running upgrade 001_initial_m2_tables -> 002_m4_practice_document_tracking, m4_practice_document_tracking
-- Running upgrade 001_initial_m2_tables -> 002_m4_practice_document_tracking

CREATE TABLE IF NOT EXISTS practice_documents (
            id SERIAL PRIMARY KEY,
            document_id VARCHAR(256) NOT NULL DEFAULT '',
            academic_year VARCHAR(32) NOT NULL,
            file_name VARCHAR(256) NOT NULL,
            file_path VARCHAR(512) NOT NULL,
            document_type VARCHAR(64) NOT NULL,
            qdrant_collection VARCHAR(128) NOT NULL,
            checksum VARCHAR(64) NOT NULL DEFAULT '',
            status VARCHAR(32) NOT NULL DEFAULT 'processed',
            chunks_count INTEGER NOT NULL DEFAULT 0,
            vectors_count INTEGER NOT NULL DEFAULT 0,
            metadata JSON,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        );

ALTER TABLE practice_documents ADD COLUMN IF NOT EXISTS document_id VARCHAR(256) NOT NULL DEFAULT '';

ALTER TABLE practice_documents ADD COLUMN IF NOT EXISTS checksum VARCHAR(64) NOT NULL DEFAULT '';

ALTER TABLE practice_documents ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'processed';

ALTER TABLE practice_documents ADD COLUMN IF NOT EXISTS chunks_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE practice_documents ADD COLUMN IF NOT EXISTS vectors_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE practice_documents ADD COLUMN IF NOT EXISTS metadata JSON;

ALTER TABLE practice_documents ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS ix_practice_documents_academic_year ON practice_documents (academic_year);

CREATE INDEX IF NOT EXISTS ix_practice_documents_document_id ON practice_documents (document_id);

CREATE INDEX IF NOT EXISTS ix_practice_documents_checksum ON practice_documents (checksum);

CREATE INDEX IF NOT EXISTS ix_practice_documents_status ON practice_documents (status);

CREATE UNIQUE INDEX IF NOT EXISTS uq_practice_document_year_path_collection
        ON practice_documents (academic_year, file_path, qdrant_collection);

UPDATE alembic_version SET version_num='002_m4_practice_document_tracking' WHERE alembic_version.version_num = '001_initial_m2_tables';

INFO  [alembic.runtime.migration] Running upgrade 002_m4_practice_document_tracking -> 003_reconcile_legacy_schema, Reconcile installations created when the initial migration was a no-op.
-- Running upgrade 002_m4_practice_document_tracking -> 003_reconcile_legacy_schema

DO $$
        BEGIN
            CREATE TYPE priorityenum AS ENUM ('low', 'medium', 'high');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;;

DO $$
        BEGIN
            CREATE TYPE actionstatusenum AS ENUM ('open', 'in_progress', 'completed', 'cancelled');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;;

CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY, telegram_chat_id VARCHAR(64) UNIQUE,
            full_name VARCHAR(128) NOT NULL, preferred_language VARCHAR(10) DEFAULT 'ro', created_at TIMESTAMP);

CREATE TABLE IF NOT EXISTS academic_years (
            id SERIAL PRIMARY KEY, year_code VARCHAR(32) NOT NULL UNIQUE,
            is_active BOOLEAN DEFAULT FALSE, created_at TIMESTAMP);

CREATE TABLE IF NOT EXISTS email_accounts (
            id SERIAL PRIMARY KEY, account_type VARCHAR(32) NOT NULL,
            email_address VARCHAR(128) NOT NULL UNIQUE, is_active BOOLEAN DEFAULT TRUE);

CREATE TABLE IF NOT EXISTS emails (
            id SERIAL PRIMARY KEY, message_id VARCHAR(256) NOT NULL UNIQUE,
            account_type VARCHAR(32) NOT NULL, sender VARCHAR(256) NOT NULL,
            subject VARCHAR(512), body_text TEXT, received_at TIMESTAMP NOT NULL,
            summary TEXT, category VARCHAR(64), is_practice_related BOOLEAN DEFAULT FALSE,
            requires_action BOOLEAN DEFAULT FALSE, detected_deadline TIMESTAMP, created_at TIMESTAMP);

CREATE TABLE IF NOT EXISTS practice_questions (
            id SERIAL PRIMARY KEY, academic_year VARCHAR(32) NOT NULL,
            student_name VARCHAR(128), student_group VARCHAR(32), topic VARCHAR(128) NOT NULL,
            question_summary TEXT NOT NULL, source_type VARCHAR(64) NOT NULL,
            source_reference VARCHAR(256), tags JSON, created_at TIMESTAMP);

CREATE TABLE IF NOT EXISTS practice_answers (
            id SERIAL PRIMARY KEY, question_id INTEGER NOT NULL REFERENCES practice_questions(id) ON DELETE CASCADE,
            answer_summary TEXT NOT NULL, decision VARCHAR(128), academic_year VARCHAR(32) NOT NULL, created_at TIMESTAMP);

CREATE TABLE IF NOT EXISTS action_items (
            id SERIAL PRIMARY KEY, title VARCHAR(256) NOT NULL, source VARCHAR(64) NOT NULL,
            deadline TIMESTAMP, priority priorityenum DEFAULT 'medium', status actionstatusenum DEFAULT 'open',
            source_reference VARCHAR(256), created_at TIMESTAMP);

CREATE TABLE IF NOT EXISTS conversations (
            id SERIAL PRIMARY KEY, telegram_chat_id VARCHAR(64) NOT NULL,
            session_id VARCHAR(64) NOT NULL UNIQUE, created_at TIMESTAMP);

CREATE TABLE IF NOT EXISTS conversation_messages (
            id SERIAL PRIMARY KEY, conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            sender_role VARCHAR(32) NOT NULL, content TEXT NOT NULL, tool_calls JSON, created_at TIMESTAMP);

CREATE TABLE IF NOT EXISTS user_memories (
            id SERIAL PRIMARY KEY, key VARCHAR(128) NOT NULL UNIQUE, value TEXT NOT NULL,
            category VARCHAR(64), created_at TIMESTAMP);

CREATE TABLE IF NOT EXISTS news_articles (
            id SERIAL PRIMARY KEY, title VARCHAR(512) NOT NULL, url VARCHAR(1024) NOT NULL UNIQUE,
            topic VARCHAR(64) NOT NULL, relevance_score DOUBLE PRECISION DEFAULT 0,
            summary TEXT, published_at TIMESTAMP, created_at TIMESTAMP);

CREATE TABLE IF NOT EXISTS audit_logs (
            id SERIAL PRIMARY KEY, timestamp TIMESTAMP, user_request TEXT, selected_tool VARCHAR(128),
            model_used VARCHAR(64), status VARCHAR(32) NOT NULL, execution_duration_ms DOUBLE PRECISION,
            external_operation VARCHAR(256), rag_sources JSON);

CREATE INDEX IF NOT EXISTS ix_users_id ON users (id);

CREATE INDEX IF NOT EXISTS ix_users_telegram_chat_id ON users (telegram_chat_id);

CREATE INDEX IF NOT EXISTS ix_academic_years_id ON academic_years (id);

CREATE INDEX IF NOT EXISTS ix_academic_years_year_code ON academic_years (year_code);

CREATE INDEX IF NOT EXISTS ix_email_accounts_id ON email_accounts (id);

CREATE INDEX IF NOT EXISTS ix_emails_id ON emails (id);

CREATE INDEX IF NOT EXISTS ix_emails_message_id ON emails (message_id);

CREATE INDEX IF NOT EXISTS ix_practice_questions_id ON practice_questions (id);

CREATE INDEX IF NOT EXISTS ix_practice_questions_academic_year ON practice_questions (academic_year);

CREATE INDEX IF NOT EXISTS ix_practice_answers_id ON practice_answers (id);

CREATE INDEX IF NOT EXISTS ix_practice_answers_academic_year ON practice_answers (academic_year);

CREATE INDEX IF NOT EXISTS ix_action_items_id ON action_items (id);

CREATE INDEX IF NOT EXISTS ix_conversations_id ON conversations (id);

CREATE INDEX IF NOT EXISTS ix_conversations_telegram_chat_id ON conversations (telegram_chat_id);

CREATE INDEX IF NOT EXISTS ix_conversation_messages_id ON conversation_messages (id);

CREATE INDEX IF NOT EXISTS ix_user_memories_id ON user_memories (id);

CREATE INDEX IF NOT EXISTS ix_user_memories_key ON user_memories (key);

CREATE INDEX IF NOT EXISTS ix_news_articles_id ON news_articles (id);

CREATE INDEX IF NOT EXISTS ix_audit_logs_id ON audit_logs (id);

UPDATE alembic_version SET version_num='003_reconcile_legacy_schema' WHERE alembic_version.version_num = '002_m4_practice_document_tracking';

INFO  [alembic.runtime.migration] Running upgrade 003_reconcile_legacy_schema -> 004_persist_pending_email_drafts, Persist email drafts awaiting explicit human approval.
-- Running upgrade 003_reconcile_legacy_schema -> 004_persist_pending_email_drafts

CREATE TABLE pending_email_drafts (
    id SERIAL NOT NULL, 
    draft_id VARCHAR(64) NOT NULL, 
    owner_id VARCHAR(64) NOT NULL, 
    original_message_id VARCHAR(256) NOT NULL, 
    account_type VARCHAR(32) NOT NULL, 
    recipient VARCHAR(512) NOT NULL, 
    subject VARCHAR(512) NOT NULL, 
    body TEXT NOT NULL, 
    metadata JSON, 
    status VARCHAR(32) DEFAULT 'pending_approval' NOT NULL, 
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
    decided_at TIMESTAMP WITHOUT TIME ZONE, 
    PRIMARY KEY (id), 
    UNIQUE (draft_id)
);

CREATE INDEX ix_pending_email_drafts_id ON pending_email_drafts (id);

CREATE UNIQUE INDEX ix_pending_email_drafts_draft_id ON pending_email_drafts (draft_id);

CREATE INDEX ix_pending_email_drafts_owner_id ON pending_email_drafts (owner_id);

CREATE INDEX ix_pending_email_drafts_status ON pending_email_drafts (status);

UPDATE alembic_version SET version_num='004_persist_pending_email_drafts' WHERE alembic_version.version_num = '003_reconcile_legacy_schema';

COMMIT;

