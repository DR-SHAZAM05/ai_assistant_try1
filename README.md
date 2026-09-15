# Personal Academic AI Assistant

Asistent AI modular dezvoltat pentru mediul academic (studenți și cadre didactice UNITBV), capabil să interacționeze printr-o interfață conversațională de Telegram cu e-mailul personal, e-mailul instituțional UNITBV, Google Calendar, surse configurabile de știri și o bază de cunoștințe de practică structurată pe ani universitari.

## Project Overview

Personal Academic AI Assistant rezolvă problema fragmentării informațiilor academice prin centralizarea accesului la multiple canale de comunicație și informație: e-mail personal și instituțional, calendar Google, documente de practică, termene limită, știri tehnologice și actualizări.

Sistemul folosește o arhitectură modulară bazată pe microservicii cu AI Orchestrator central, RAG (Retrieval-Augmented Generation) pentru răspunsuri bazate pe documente oficiale, și Human-in-the-Loop pentru acțiuni externe critice.

## Features Actuale

- **AI Orchestrator Central**: Intent detection, tool selection, routing, și coordonare multi-agent
- **Telegram Integration**: Interfață conversațională naturală cu webhook, comenzi, și inline keyboards
- **PostgreSQL Persistence**: 16 tabele pentru conversații, email-uri, sarcini, memorie, audit
- **User Isolation**: Izolare completă a datelor pe utilizatori în toate componentele
- **RAG Knowledge Base**: Căutare semantică în documente de practică organizate pe ani universitari
- **Multi-year Academic Information**: Structură general/ și pe ani (2024-2025, 2025-2026, 2026-2027)
- **Ollama Integration**: Local LLM runtime pentru fallback (nomic-embed-text, qwen2.5:1.5b)
- **Qdrant Vector Database**: Embeddings vectoriali cu cosine similarity și metadata filtering
- **Google Calendar Integration**: Event listing, creation, update, delete cu HITL complet
- **Human-in-the-Loop**: Confirmare obligatorie pentru email și calendar modificări
- **Email Workflow**: IMAP provider pentru email personal cu deduplicare și clasificare
- **UNITBV Microsoft Graph**: Provider implementat (DEFERRED - access token blocked extern)
- **News Agent**: RSS fetching, deduplicare, relevance scoring pentru topicuri IT și AI
- **Action Items / Tasks**: Extracție din email, calendar, practică cu persistență PostgreSQL
- **Daily Briefing**: Automation endpoint cu sinteză matinală (calendar, email, practică, sarcini, știri)
- **n8n Automation**: 4 workflow-uri programate pentru briefing, news, deadlines, email polling
- **Audit Logging**: Sanitizare automată pentru log-uri de securitate
- **Backup / Restore**: PostgreSQL dump și Qdrant snapshot cu SHA-256 verification
- **Security / Hardening**: Rate limiting, HMAC authentication, secrets management

## Architecture

Arhitectura sistemului este modulară, bazată pe microservicii cu provider abstraction pentru integrări externe:

```text
User
  ↓
Telegram / API
  ↓
AI Orchestrator
  ↓
Agents / Services
  ↓
PostgreSQL / Qdrant / Ollama
  ↓
External Integrations
```

### Componente Principale

- **Telegram Bot**: Interfață utilizator cu webhook și inline keyboards
- **FastAPI API**: API Gateway cu endpoint-uri pentru webhook și automatizări
- **AI Orchestrator**: Intent detection, tool registry, routing, context management
- **Agents**: EmailAgent, CalendarAgent, NewsAgent, PracticeAgent
- **Services**: EmailService, CalendarService, NewsService, ActionItemService
- **PostgreSQL**: Relațional database pentru persistență
- **Qdrant**: Vector database pentru RAG
- **Ollama**: Local LLM runtime pentru fallback
- **n8n**: Automation engine pentru joburi programate

## Technology Stack

| Technology | Purpose |
|------------|---------|
| Python 3.14 | Backend language |
| FastAPI 0.141.1 | API framework |
| PostgreSQL 16 | Relational database |
| SQLAlchemy 2.0.52 | ORM |
| Alembic 1.19.1 | Database migrations |
| Qdrant 1.19.0 | Vector database |
| Ollama 0.33.1 | Local LLM / embeddings |
| Telegram Bot API 22.8 | User interaction |
| Google Calendar API v3 | Calendar integration |
| Microsoft Graph API | UNITBV email (deferred) |
| n8n 2.37.4 | Automation |
| Docker Compose | Deployment |
| pytest 9.1.1 | Testing |

## Project Structure

```
ai_assistant_try1/
├── README.md
├── .env.example
├── .gitignore
├── .dockerignore
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── pyproject.toml
│
├── automation/
│   └── workflows/
│       ├── daily_briefing.json
│       ├── daily_email_poll.json
│       ├── daily_news_refresh.json
│       └── practice_deadline_reminder.json
│
├── config/
│   ├── news.yaml
│   ├── news.example.yaml
│   ├── practice.yaml
│   └── practice.example.yaml
│
├── scripts/
│   ├── run_automation.py
│   ├── backup.py
│   ├── restore.py
│   ├── retention.py
│   ├── verify_restore.py
│   ├── verify_acceptance.py
│   ├── verify_phase2_persistence.py
│   └── authorize_google_calendar.py
│
├── src/
│   └── app/
│       ├── main.py
│       ├── api/routes/
│       ├── core/
│       ├── orchestrator/
│       ├── agents/
│       ├── llm/
│       ├── integrations/
│       ├── rag/
│       ├── memory/
│       ├── database/
│       └── services/
│
├── database/migrations/
├── knowledge_base/
│   ├── general/
│   ├── 2024-2025/
│   ├── 2025-2026/
│   └── 2026-2027/
├── docs/
└── tests/
```

## Installation

### Prerequisites
- Docker Desktop și Docker Compose
- Git

### 1. Clone repository
```bash
git clone <repository-url>
cd ai_assistant_try1
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env cu valorile tale
```

### 3. Start infrastructure
```bash
docker compose up -d postgres qdrant n8n ollama
```

### 4. Initialize Ollama models
```bash
docker compose run --rm ollama-init
```

### 5. Run migrations
```bash
docker compose --profile tools run --rm migrate
```

### 6. Start application
```bash
docker compose up -d --build app
```

### 7. Ingest RAG documents
```bash
docker compose exec app python -m src.app.rag.ingest
```

## Configuration

Variabile importante din `.env.example` (fără valori secrete):

- `APP_ENV`: development / production
- `SECRET_KEY`: Secret pentru signing
- `TELEGRAM_BOT_TOKEN`: Token bot Telegram
- `TELEGRAM_WEBHOOK_SECRET`: Secret pentru webhook HMAC
- `TELEGRAM_ALLOWED_USER_IDS`: User IDs permise
- `OPENAI_API_KEY`: Cheie OpenAI/Gemini
- `POSTGRES_*`: Configurare PostgreSQL
- `QDRANT_*`: Configurare Qdrant
- `LLM_PROVIDER`: openai / ollama
- `EMBEDDING_PROVIDER`: openai / ollama
- `CURRENT_ACADEMIC_YEAR`: An universitar curent
- `BACKUP_DIR`: Director backup
- `BACKUP_RETENTION_DAYS`: Zile retenție
- `AUTOMATION_API_KEY`: Cheie pentru n8n

## Running the Project

```bash
# Start services
docker compose up -d

# Stop services
docker compose down

# View logs
docker compose logs

# Run tests
docker compose exec app pytest -v

# Run migrations
docker compose --profile tools run --rm migrate

# Backup
python -m scripts.backup

# Restore
python -m scripts.restore <timestamp>

# Daily briefing
python scripts/run_automation.py --job briefing
```

## Testing

**Test Results: 234 passed, 0 failed, 10 skipped**

Cele 10 teste skipped sunt marcate automat când condițiile necesare nu sunt disponibile (RUN_LIVE_RAG=false, servicii externe indisponibile, configurații lipsă). Acestea NU sunt failures.

```bash
# Run tests
pytest -v

# Run with coverage
pytest --cov=src --cov-report=html
```

## Current Implementation Status

| Phase | Status |
|-------|--------|
| Phase 1 | PASS / LIVE VERIFIED |
| Phase 2 | PASS / LIVE VERIFIED |
| Phase 3 | DEFERRED / BLOCKED |
| Phase 4 | PASS / LIVE VERIFIED |
| Phase 5 | PASS / LIVE VERIFIED |
| Phase 6 | PASS / LIVE VERIFIED |
| Phase 7 | PASS / LIVE VERIFIED |
| Phase 8 | PASS / LIVE VERIFIED |
| Phase 9 | PASS / LIVE VERIFIED |
| Phase 10 | PASS |

## UNITBV Limitation

**UNITBV Microsoft Graph Email — DEFERRED / BLOCKED BY EXTERNAL ACCOUNT ACCESS**

Provider-ul Microsoft Graph este complet implementat în cod (UnitbvGraphProvider). OAuth2 Authorization Code flow este funcțional. Authorization URL poate fi generat. Access token nu a putut fi obținut din cauza blocării temporare a contului instituțional de către Microsoft/UNITBV. Aceasta este o limitare externă, nu o problemă de implementare.

## Backup / Restore

- **scripts/backup.py**: PostgreSQL dump + Qdrant snapshot cu SHA-256
- **scripts/restore.py**: Restaurare cu verificare integritate
- **scripts/retention.py**: Politică de retenție pentru backup-uri vechi
- **scripts/verify_restore.py**: Verificare restore în containere izolate temporare
- **SHA-256**: Verificare criptografică pentru fiecare fișier
- **PostgreSQL dump**: pg_dump --format=custom
- **Qdrant snapshot**: Snapshot API
- **Isolated restore**: Verificare în containere temporare (PostgreSQL:15432, Qdrant:16333)

**Note**: Production restore nu a fost live verificat. Script-ul existent și funcțional, dar restore în producție nu a fost testat.

## Security

- **Qdrant API authentication**: API key pentru vector database
- **Telegram HMAC**: Webhook secret pentru verification
- **Automation authentication**: X-Automation-Key cu HMAC comparison
- **User isolation**: user_id în toate tabelele și Qdrant metadata filters
- **Human-in-the-Loop**: Confirmare obligatorie pentru acțiuni externe
- **Audit sanitization**: Redactare automată a email, phone, tokens din audit
- **Secrets management**: .env exclus din Git
- **Rate limiting**: Token bucket algorithm
- **Prompt injection protection**: Context management și input validation
- **Database transaction safety**: SQLAlchemy session management

## n8n Automation

4 workflow-uri implementate:

| Workflow | Trigger | Endpoint | Scop |
|----------|---------|-----------|------|
| Daily Briefing | Cron daily 08:00 | /automation/daily-briefing | Sinteză matinală |
| Daily News Refresh | Cron daily 08:00 | /automation/news/refresh | Articole noi |
| Practice Deadline Reminder | Cron daily 09:00 | /automation/practice/deadlines-check | Alerte deadline |
| Daily Email Poll | Cron every 2h | /automation/email/poll | Verificare email |

Authentication: X-Automation-Key header cu HMAC comparison. User isolation prin telegram_user_id.

## RAG / Knowledge Base

**Pipeline**: Question → Embedding → Qdrant Search → Filters (academic_year, user_id) → Relevant Chunks → Grounded Answer

- **Ingestion**: PDF, TXT, MD cu SHA-256 checksum pentru deduplicare
- **Chunking**: 800 tokens, 100 overlap
- **Embeddings**: nomic-embed-text (768 dim) sau text-embedding-3-small (1536 dim)
- **Qdrant**: Vector database cu cosine similarity
- **Metadata**: academic_year, user_id, document_type, source_path
- **Academic year filtering**: Informație anuală + generală
- **User filtering**: Documente utilizatorului + globale
- **Semantic search**: Cosine similarity cu score threshold 0.35
- **Grounded answers**: Source attribution pentru prevenirea halucinațiilor

## Usage Examples

**Întrebare academică**:
```
Cum se completează convenția de practică?
```

**Căutare în Knowledge Base**:
```
Caută informații despre practica din 2026-2027
```

**Calendar**:
```
/calendar
Ce am mâine în calendar?
```

**Creare task**:
```
Adaugă sarcină: depune convenția până pe 28 august
```

**Listare task-uri**:
```
/sarcini
Ce mai am de făcut?
```

**Briefing**:
```
/briefing
Sinteza mea de astăzi
```

**News**:
```
/stiri
Arată-mi știrile despre AI
```

**Email draft/HITL**:
```
Răspunde la mail-ul de la profesor
[Preview draft] → [Răspunde] [Anulează]
```

**Telegram commands**:
```
/calendar - Program calendar
/email - Verificare email-uri
/sarcini - Listare sarcini
/stiri - Știri tehnologice
/practice - Întrebări practică
/briefing - Sinteză matinală
```

## Known Limitations

1. **UNITBV Microsoft Graph**: DEFERRED - Provider implementat, access token blocked extern de Microsoft/UNITBV
2. **Production restore**: NOT LIVE VERIFIED - Script existent, neverificat în producție
3. **Skipped tests**: 10 teste SKIPPED - condiții live indisponibile (RUN_LIVE_RAG=false, servicii externe)
4. **Single-threaded Ollama**: Nu este paralelizat
5. **Qdrant mock fallback**: Doar pentru development, nu pentru production
6. **No web UI**: Doar Telegram interfață principală

## Documentation

Documentație tehnică completă: `Personal_Academic_AI_Assistant_Documentatie_Finala_Professional.docx`

Include:
- Arhitectură detaliată
- Tehnologii utilizate
- Structura proiectului
- Implementarea completă
- Testing și verification
- Deployment guide
- Configuration reference
- API endpoints
- n8n workflows
- Test matrix
- Glosar

## License

Proiect academic dezvoltat pentru practica studențească la UNITBV.
