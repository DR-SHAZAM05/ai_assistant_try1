# Documentație Arhitectură System - Personal Academic AI Assistant

## 1. Context și Viziune

Sistemul **Personal Academic AI Assistant** este conceput ca o aplicație modulară, decuplată și extrem de configurabilă. Asistentul servește drept hub central conversational (prin Telegram) pentru activitatea academică și personală a studentului / cadrului didactic UNITBV, agregând date din e-mail-uri, calendar, fișiere de practică, surse de știri și memorii istorice.

---

## 2. Diagrame de Componente

```text
                                +---------------------------+
                                |      Telegram Client      |
                                +-------------+-------------+
                                              |
                                              v  HTTP Webhook / Polling
                                +-------------+-------------+
                                |    FastAPI Webhook & API  |
                                |         Gateway           |
                                +-------------+-------------+
                                              |
                                              v  User Request + Context
                                +-------------+-------------+
                                |      AI Orchestrator      |
                                | (Intent Detection & Tools)|
                                +-------------+-------------+
                                              |
        +-----------------------+-------------+-----------------------+
        |                       |             |                       |
        v                       v             v                       v
+---------------+       +---------------+ +---------------+   +---------------+
|  Email Agent  |       |Calendar Agent | |Practice Agent |   |  News Agent   |
+-------+-------+       +-------+-------+ +-------+-------+   +-------+-------+
        |                       |                 |                   |
        v                       v                 v                   v
+---------------+       +---------------+ +---------------+   +---------------+
|IMAP/SMTP/Graph|       |Google Calendar| |  RAG Engine   |   | RSS / Web     |
| (Personal &   |       |      API      | | Vector Store  |   | News Fetcher  |
|    UNITBV)    |       +---------------+ +-------+-------+   +---------------+
+---------------+                                 |
                                                  v
                                          +---------------+
                                          | PostgreSQL DB |
                                          |  & Qdrant DB  |
                                          +---------------+
```

---

## 3. Descrierea Modulelor Principale

### 3.1. FastAPI Gateway (`src/app/main.py`, `src/app/api/`)
- Punctul de recepție al webhook-urilor trimise de Telegram (sau de către un proxy n8n).
- Autentifică request-urile și validează payload-ul prin scheme Pydantic.
- Inițializează sesiunile de bază de date și pasează mesajul către Orchestrator.

### 3.2. AI Orchestrator (`src/app/orchestrator/`)
- Inima inteligentă a aplicației.
- Analizează limbajul natural al utilizatorului și identifică **Intenția (Intent)** și **Tool-urile necesare**.
- Suportă apelarea concomitentă sau secvențială a mai multor agenți (ex: `Ce am mâine?` -> Calendar Agent + Action Items Agent).
- Sintetizează răspunsurile primite de la agenți într-un mesaj coerent livrat utilizatorului.

### 3.3. LLM Abstraction Layer (`src/app/llm/`)
- Clasă abstractă `LLMProvider` cu două implementări concrete:
  1. `OpenAIProvider`: Apel direct către API-ul Cloud (OpenAI / Gemini).
  2. `OllamaProvider`: Apel local către un runtime Ollama (pentru Phase II).
- Permite schimbarea din `.env` (`LLM_PROVIDER=openai` sau `LLM_PROVIDER=ollama`) fără a modifica nicio linie de cod din business logic.

### 3.4. Email Agent & UNITBV Practice Integrator (`src/app/agents/email_agent.py`)
- Gestionează conectarea la contul personal și contul instituțional `@student.unitbv.ro`.
- Realizează citirea, sumarizarea, clasificarea e-mailurilor și detecția acțiunilor/deadline-urilor.
- Identifică e-mailurile referitoare la practică și le direcționează către `Practice Agent`.
- Generează draft-uri de răspuns și solicită aprobare umană (*Human-in-the-Loop*) înainte de trimitere.

### 3.5. Practice Agent & RAG Engine (`src/app/agents/practice_agent.py`, `src/app/rag/`)
- Gestionează Knowledge Base-ul structurat pe **ani universitari** (ex: `2025-2026`, `2026-2027`).
- Extrage text din PDF, TXT si Markdown, efectuează chunking configurabil și generează embeddings vectoriale.
- Stochează vectorii în **Qdrant** având ca filtru meta-data `academic_year`.
- Persistă metadata documentelor în PostgreSQL prin `practice_documents`: `document_id`, `academic_year`, `file_path`, `checksum`, `status`, `chunks_count`, `vectors_count`.
- Răspunde la întrebări indicând sursele folosite. Dacă retrieval-ul nu găsește context relevant peste pragul configurat, agentul returnează explicit că informația nu este disponibilă în documentele existente.

Fluxul RAG M4:

```text
Telegram
  -> FastAPI webhook
  -> Orchestrator
  -> Practice Agent
  -> RAG Retriever
  -> EmbeddingProvider
  -> Qdrant search filter academic_year
  -> LLMProvider sau raspuns extractiv local
  -> Response + Sources
```

Fluxul de ingestion:

```text
knowledge_base/<academic_year>/
  -> extract text PDF/TXT/MD
  -> normalize text
  -> chunk
  -> checksum SHA-256
  -> PracticeDocument lookup
  -> skip unchanged OR delete old vectors for modified document
  -> embed chunks
  -> upsert Qdrant
  -> update PracticeDocument
```

### 3.6. Calendar Agent (`src/app/agents/calendar_agent.py`)
- Conector OAuth / Service Account cu Google Calendar API.
- Oferă consultare program zilnic/săptămânal, verificare intervale libere și propuneri de evenimente.
- Orice creare, modificare sau ștergere de eveniment solicită confirmare din Telegram.

### 3.7. News Agent (`src/app/agents/news_agent.py`)
- Prelucrează surse RSS/Web definite în `config/news.yaml`.
- Clasifică articolele pe topicuri (AI, Embedded, UNITBV), calculează un scor de relevanță și generează rezumate.

### 3.8. Memory & Action Items (`src/app/memory/`)
- **Conversation Memory**: Păstrează istoricul conversației curente pe sesiuni Telegram pentru a înțelege întrebări anafalice (ex: "Și după al doilea?").
- **Long-term User Memory**: Stochează preferințele utilizatorului, expeditorii importanți și regulile custom.
- **Action Items**: Centralizează task-urile extrase din e-mail-uri, calendar și practică.

---

## 4. Schemă Bază de Date PostgreSQL (Modele SQLAlchemy)

Modelele de date principale definite în `src/app/database/models/`:

1. **`users`**: Informații utilizator, Telegram Chat ID, preferințe.
2. **`academic_years`**: Lista anilor universitari (ex: `2025-2026`, status active/archived).
3. **`email_accounts`**: Credențiale și setări servere IMAP/SMTP (personal / UNITBV).
4. **`emails`**: Mesaje descărcate, sumar, categorie, flag-uri (`is_practice`, `requires_action`).
5. **`practice_questions` & `practice_answers`**: Istoric întrebări și răspunsuri oferite studenților cu tagging și legătură la anul universitar.
6. **`practice_documents`**: Fișiere ingestate în RAG, checksum persistent, status de procesare, număr de chunks/vectori și referință la colecția Qdrant.
7. **`action_items`**: Task-uri extrase cu titlu, sursă, deadline, prioritate și status.
8. **`conversations` & `conversation_messages`**: Memorie conversație Telegram.
9. **`user_memories`**: Reguli și preferințe pe termen lung stocate de utilizator.
10. **`news_articles`**: Articole de știri preluate, scor relevanță și sumar.
11. **`audit_logs`**: Log-uri de securitate și trasabilitate (timestamp, user, intent, tool, status, model).
12. **`practice_documents`**: Checksum-uri și metadate fișiere KB pentru ingestie incrementală.

---

## 4. Module Extinse & Arhitectură Rezilientă

### 4.1. Generare Documente Oficiale de Practică (`DocumentGeneratorService`)
- Sistem nativ de generare a documentelor Microsoft Word (`.docx`) folosind `python-docx`.
- `DocumentTemplateRegistry` gestionează șabloanele predefinite:
  - `conventie_cadru_practica`: Convenție-cadru de colaborare pentru practică student/universitate/partener.
  - `caiet_practica_fiesc`: Caietul oficial de practică FIESC (structură completă: date generale, obiective, orar zilnic pe 3 săptămâni, concluzii, evaluare tutore).
- Livrare binară directă pe canalul de Telegram prin `sendDocument`, fără a fi necesară salvarea fișierelor pe disc într-o zonă publică.

### 4.2. UI Interactiv Telegram & Butoane Human-in-the-Loop
- **Tastatură Persistentă (ReplyKeyboardMarkup):** Acces rapid dintr-o singură atingere pentru modulele principale: `[ 📄 Practică UNITBV ]`, `[ 📅 Calendar & Orar ]`, `[ 📋 Sarcini & Task-uri ]`, `[ 📧 E-mail ]`, `[ 📰 Știri IT & AI ]`.
- **Butoane Inline de Acțiune Directă (InlineKeyboardMarkup):**
  - **Email Action Buttons:** La listarea mesajelor, utilizatorul primește butonul `[ ✉️ Răspunde ]`.
  - **Draft Human Approval:** Drafturile generate de asistent prezintă butoane inline de aprobare sau respingere (`[ ✉️ Trimite ]` / `[ ❌ Anulează ]`).
  - **Task Completion:** Notificările și listele de sarcini oferă acțiune rapidă de bifare (`[ ✅ Finalizează #ID ]`).
  - **Limită 64-byte Telegram:** Sistemul folosește indici scurți (`reply_mail:{idx}`) și trunchiere sigură pentru a respecta constrângerea de 64 de bytes a Telegram Bot API.

### 4.3. Arhitectură Hibridă Rezilientă LLM (Cloud ↔ Local Ollama)
- Sistem decuplat în jurul interfeței abstracte `LLMProvider`.
- Permite comutarea între Google Gemini / OpenAI (`OpenAIProvider`) și Docker Ollama (`OllamaProvider`).
- **Failover Transparent:** În cazul în care providerul cloud întâmpină erori de rețea, timeout sau epuizarea cotei de utilizare (`HTTP 429 RateLimitError` / Quota Exceeded), `OpenAIProvider` prinde excepția și apelează automat runtime-ul local `academic_ai_ollama` (`qwen2.5:1.5b`), garantând disponibilitate 100% fără intervenție manuală.

### 4.4. Notificări Proactive & Programate (n8n & CLI)
- Arhitectură bazată pe webhook-uri securizate prin `X-Automation-Key`:
  - `POST /api/v1/automation/daily-briefing`: Agregare automată (evenimente calendar + sarcini nerezolvate + top știri) cu livrare push pe Telegram.
  - `POST /api/v1/automation/practice/deadlines-check`: Calcul dinamic al proximității jaloanelor oficiale UNITBV (28 august, 2 septembrie, 5-10 septembrie) cu butoane inline.
  - `POST /api/v1/automation/news/refresh`: Preluare și deduplicare fluxuri RSS.
  - `POST /api/v1/automation/email/poll`: Monitorizare căsuțe și alertă push pe Telegram la mesaje urgente.
- **CLI Unificat `scripts/run_automation.py`:** Permite rularea oricărui flux manual sau automatizat prin cron/Task Scheduler (`--job deadlines|briefing|news|email|backup|all`).

### 4.5. Disaster Recovery & Backup Criptografic
- Procedură automatizată completă de salvare (`scripts/backup.py`) și restaurare (`scripts/restore.py`).
- Salvează baza de date PostgreSQL într-un dump binar custom (`postgres.dump`) și colecția vectorială Qdrant într-un fișier snapshot (`qdrant.snapshot`).
- Calculează sumele de control **SHA-256** stocate în `manifest.json`.
- La restaurare, scriptul verifică integritatea fiecărui artefact și cere confirmare explicită (`--yes`) înainte de a suprascrie datele curente.

---

## 5. Diagrame de Flux (Sequence Diagrams)

### Scenario 1: Interogare Practică cu RAG și An Universitar Anterior

```text
User (Telegram)              FastAPI Gateway            Orchestrator               Practice Agent / RAG Engine         Qdrant / Postgres
     |                             |                          |                                 |                             |
     |--- "Ce am răspuns anul ---->|                          |                                 |                             |
     |    trecut despre Erasmus?"  |--- Process Telegram ---->|                                 |                             |
     |                             |    Webhook               |--- Detect Intent:               |                             |
     |                             |                          |    PRACTICE_HISTORICAL_QUERY -->|                             |
     |                             |                          |                                 |--- Embed Query & Query ---->|
     |                             |                          |                                 |    Filter: year=2025-2026   |
     |                             |                          |                                 |<-- Return Chunks & Answers -|
     |                             |                          |                                 |                             |
     |                             |                          |<-- Return Context & Sources ----|                             |
     |                             |<-- LLM Synthesized ------|                                                               |
     |                             |    Answer + Citations    |                                                               |
     |<-- Send Telegram Response --|                          |                                                               |
```

### Scenario 2: Integrare Email UNITBV ↔ Practică + Human Approval

```text
Student Email               UNITBV Email Agent         Practice Agent             AI Orchestrator             User Telegram
      |                             |                         |                          |                          |
      |--- New Email Received ----->|                         |                          |                          |
      |    "Caiet de practică"      |--- Classify Email ------>|                          |                          |
      |                             |    (Practice Detected)  |--- Search KB & Historical|                          |
      |                             |                         |    Answers               |                          |
      |                             |                         |--- Generate Draft ------>|                          |
      |                             |                         |    Reply                 |--- Send Notification ---->|
      |                             |                         |                          |    "Am generat draft:    |
      |                             |                         |                          |     Trimitem răspunsul?" |
      |                             |                         |                          |     [ DA ]   [ NU ]      |
      |                             |                         |                          |                          |
      |                             |                         |<============================== User Clicks [ DA ] ===|
      |                             |<-- Approved ------------|                          |                          |
      |<-- Send Approved Email -----|                         |                          |                          |
      |                             |                         |--- Save Answer Summary ->| (Saved into KB 2026-2027) |
```

---

## 6. Strategie de Securitate și Transmisibilitate

1. **Izolarea Medilor**: Fișierul `.env` este complet izolat și nu se include în versiunile Git.
2. **Zero Credentials in Code**: Niciun token Telegram, parolă de mail sau cheie API nu este salvată în codul sursă.
3. **Portabilitate pe altă Mașină**:
   - Proiectul conține `docker-compose.yml` complet pentru servicii.
   - Fișierele de configurare din `config/` permit schimbarea topicurilor de știri și regulilor de practică.
   - Schimbarea anului universitar se face din variabila `CURRENT_ACADEMIC_YEAR`.

---

## 7. Organizarea și Partajarea Rolurilor în Echipă (Cerințele 24 & 25)

Arhitectura modulară a fost proiectată explicit pentru a permite dezvoltarea paralelă, decuplată și fără conflicte Git, atât pentru echipe formate din 3 studenți, cât și pentru echipe formate din 2 studenți.

### 7.1. Scenariul pentru Echipă de 3 Studenți (Secțiunea 24)

```text
+---------------------------------------------------------------------------------+
|                                 ECHIPA DE 3 STUDENȚI                             |
+---------------------------------------------------------------------------------+
|  STUDENT 1: Core & Orchestration                                                |
|  - FastAPI Webhook & API Gateway (`src/app/api/`)                               |
|  - Telegram Bot & UI Interactiv (`src/app/integrations/telegram/`)              |
|  - Tastatură persistentă & butoane inline (64-byte safe callbacks)              |
|  - AI Orchestrator & Intent Router (`src/app/orchestrator/`)                    |
|  - Baza de date PostgreSQL (schema inițială, modele, migrare)                   |
|  - LLM Provider Layer (Gemini/OpenAI + fallback transparent Ollama)             |
+---------------------------------------------------------------------------------+
|  STUDENT 2: Communication & Integrations                                        |
|  - Modulul E-mail (`src/app/services/email_service.py`, `email_agent.py`)       |
|  - Suport cont dublu: E-mail Personal + E-mail Instituțional UNITBV             |
|  - Conector Google Calendar API v3 (`calendar_service.py`, `calendar_agent.py`) |
|  - Verificare disponibilitate intervale orare & propunere evenimente            |
|  - Action Items Extractor & Human-in-the-Loop (aprobare draft-uri / calendar)  |
+---------------------------------------------------------------------------------+
|  STUDENT 3: Knowledge, Practice, News & Memory                                  |
|  - RAG Pipeline: Ingestion, Chunking, Embeddings & Qdrant Vector Store          |
|  - Structură Multi-anuală KB (2024-2025, 2025-2026, 2026-2027 + Regulament)    |
|  - Practice Agent (`src/app/agents/practice_agent.py`)                          |
|  - Generator Oficial Word (`.docx`) pentru Convenție și Caiet de Practică       |
|  - News Agent RSS/Web dinamic (`config/news.yaml`)                              |
|  - Memorie Conversațională (istoric anafalic) & Memorie de Preferințe (reguli)  |
+---------------------------------------------------------------------------------+
```

### 7.2. Scenariul pentru Echipă de 2 Studenți (Secțiunea 25)

```text
+---------------------------------------------------------------------------------+
|                                 ECHIPA DE 2 STUDENȚI                             |
+---------------------------------------------------------------------------------+
|  STUDENT A: Core, Telegram, E-mail, Calendar & Local LLM                        |
|  - FastAPI Gateway, Rute Telegram Webhook & Healthchecks                        |
|  - Interfață Telegram Bot (Meniu persistent, butoane inline de acțiune)         |
|  - AI Orchestrator & Routing de intenții multi-tool                             |
|  - Conectori E-mail (Personal + UNITBV) cu detecție automată urgențe            |
|  - Google Calendar API v3 (consultare orar, creare, intervale orare)            |
|  - Provider Hibrid LLM (Cloud OpenAI/Gemini cu failover automat Ollama local)   |
|  - Fluxul Human-in-the-Loop pentru trimitere mesaje și programare evenimente    |
+---------------------------------------------------------------------------------+
|  STUDENT B: Practică, RAG, Knowledge Base, Știri, Memorie & Documente           |
|  - RAG Engine: Ingestion incrementală, chunking, checksum SHA-256, Qdrant       |
|  - Bază de cunoștințe pe ani universitari (2024-2027) + ghid general stabil     |
|  - Practice Agent & Răspunsuri la întrebări studenți cu citarea surselor        |
|  - Generator dinamic documente Microsoft Word (.docx: Convenție + Caiet)        |
|  - News Agent (crawler RSS configurabil dinamic prin `config/news.yaml`)         |
|  - Sistemul de Memorie (conversațională pe sesiuni + reguli dinamice e-mail)    |
|  - Scripturi de automatizare (n8n, Daily Briefing, Alerte Practică, Backup CLI)  |
+---------------------------------------------------------------------------------+
```

---

## 8. Concluzii și Conformitate Specificații

Arhitectura implementată garantează:
1. **Separarea strictă a responsabilităților** – fiecare agent funcționează ca un modul izolat, comunicând exclusiv prin contracte de interfață bine definite.
2. **Rezistență la căderi** – sistemul continuă să răspundă chiar dacă serviciile cloud pică (prin Ollama) sau dacă rețeaua este intermitentă.
3. **Auditabilitate și Transparență** – toate acțiunile externe sunt logate în `audit_logs`, iar acțiunile cu impact (trimitere email, creare eveniment) necesită confirmare explicită din partea utilizatorului.

