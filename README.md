# Personal Academic AI Assistant

Asistent AI personal, modular și extensibil dedicat mediului academic (studenți și cadre didactice UNITBV), capabil să interacționeze prin interfață conversațională Telegram cu e-mailul personal, e-mailul instituțional UNITBV, Google Calendar, surse de știri configurabile, un Knowledge Base de practică pe ani universitari și un sistem de memorie și action items.

---

## 🌟 Caracteristici Cheie

- **Interfață conversațională Telegram**: Înțelegere în limbaj natural fără comenzi rigide obligatorii, tastatură persistentă de navigare rapidă și **butoane inline de acțiune directă** (`[ ✉️ Răspunde ]`, `[ ✉️ Trimite ]`, `[ ❌ Anulează ]`, `[ ✅ Finalizează #ID ]`).
- **AI Orchestrator Central**: Detecție automată de intenții și executare multi-tool (Email, Calendar, Practică, Ştiri, Task-uri, Generare Documente).
- **Generare Automată Documente Oficiale (.docx)**: Generare dinamică și descărcare directă în Telegram pentru **Convenția-cadru** și **Caietul de practică** UNITBV.
- **Integrări Email Duble**: Suport pentru contul personal și contul instituțional `@student.unitbv.ro` / `@unitbv.ro` cu extragere automată de sarcini și detectare urgențe.
- **Integrator Practică UNITBV ↔ KB**: Clasificare automată a e-mailurilor legate de practică (convenții, caiete, adeverințe, colocviu, Erasmus) și salvare de rezumate (Question/Answer summaries).
- **Practice Knowledge Base & RAG cu Ani Universitari**: Căutare semantică în regulamente și date istorice structurate pe ani școlari (ex: `2025-2026`, `2026-2027`).
- **Google Calendar Assistant**: Consultare orar și evenimente prin Google Calendar API v3 cu Service Account sau OAuth, și detectare de suprapuneri.
- **News Agent Configurabil**: Citire RSS reală din surse YAML, deduplicare și calcul de relevanță pe topicuri de interes IT și AI.
- **Human-in-the-Loop**: Confirmare obligatorie din Telegram pentru acțiuni sensibile (trimitere e-mailuri, modificare calendar) prin butoane inline de aprobare.
- **Arhitectură Hibridă Rezilientă LLM (Cloud ↔ Local Ollama Fallback)**: Suport pentru OpenAI / Google Gemini, cu **fallback automat și transparent pe modelul local Ollama (`qwen2.5:1.5b`)** în caz de erori de rețea sau depășire a cotelor API (HTTP 429).
- **Notificări Proactive & Programate (n8n & CLI)**: 4 fluxuri automate (Daily Briefing matinal, Alerte Termene Practică UNITBV, Refresh Știri, Polling E-mailuri Urgente) gestionabile prin n8n și CLI-ul `scripts/run_automation.py`.
- **Backup & Disaster Recovery Criptografic (SHA-256)**: Procedură automată de backup pentru PostgreSQL și colecția vectorială Qdrant, cu verificare SHA-256 și alertă push pe Telegram.

---

## 🏗️ Arhitectură Generală

```text
               +---------------------------------------------+
               |          Telegram Bot (UI Interactiv)       |
               | (Meniu Persistent + Butoane Inline Acțiuni) |
               +----------------------+----------------------+
                                      |
                                      v  HTTPS Webhook
               +---------------------------------------------+
               |        FastAPI Webhook & API Gateway        |
               +----------------------+----------------------+
                                      |
                                      v
               +---------------------------------------------+
               |               AI Orchestrator               |
               | (Intent Detection, Tool Registry & Context) |
               +----------------------+----------------------+
                                      |
        +------------------+----------+----------+------------------+
        |                  |                     |                  |
        v                  v                     v                  v
+---------------+  +---------------+     +---------------+  +---------------+
|  Email Agent  |  |Calendar Agent |     |Practice Agent |  |  News Agent   |
+-------+-------+  +-------+-------+     +-------+-------+  +-------+-------+
        |                  |                     |                  |
        v                  v                     v                  v
+---------------+  +---------------+     +---------------+  +---------------+
|Personal/UNITBV|  |Google Calendar|     |  RAG Engine   |  | RSS / Web     |
|    Emails     |  |   API v3      |     | Vector Store  |  | News Fetcher  |
+---------------+  +---------------+     +-------+-------+  +---------------+
                                                 |
                   +-----------------------------+
                   |
                   v
+-------------------------------------+  +-----------------------------------+
|         PostgreSQL (Relational)     |  |       Qdrant (Vector Database)    |
| - Mesaje & Memorie Conversațională  |  | - Embeddings Ghid Practică UNITBV  |
| - Sarcini & Action Items            |  | - nomic-embed-text (768 dim)       |
| - Audit Log & Verificări Ingestion  |  +-----------------------------------+
+-------------------------------------+
                   ^
                   |
+-------------------------------------+  +-----------------------------------+
|     Document Generation Engine      |  |     n8n Engine & CLI Automation   |
| - Generare Convenție Practică .docx |  | - Daily Morning Briefing          |
| - Generare Caiet de Practică .docx  |  | - Monitorizare Termene Practică   |
| - Livrare directă fișiere Telegram  |  | - scripts/run_automation.py       |
+-------------------------------------+  +-----------------------------------+
```

---

## 📁 Structura Proiectului

```text
personal-academic-ai-assistant/
│
├── README.md                      # Prezentare proiect & Ghid de pornire
├── .env.example                   # Template configurare mediu
├── .gitignore                     # Excluderi Git
├── .dockerignore                  # Excluderi din contextul de build Docker
├── Dockerfile                     # Dockerfile optimizat pentru FastAPI backend
├── docker-compose.yml             # Servicii (App, Postgres, Qdrant, n8n, Ollama)
├── requirements.txt               # Dependențe Python
├── pyproject.toml                 # Configurații proiect și pytest
│
├── automation/                    # Workflow-uri n8n exportate
│   └── workflows/
│       ├── daily_briefing.json
│       ├── email_polling.json
│       ├── news_refresh.json
│       └── practice_deadlines.json
│
├── config/                        # Fișiere YAML de configurare
│   ├── news.example.yaml
│   └── practice.example.yaml
│
├── scripts/                       # Instrumente de operare și automatizare
│   ├── run_automation.py          # CLI unificat pentru rulat joburi & briefing
│   ├── backup.py                  # Dump PostgreSQL + Snapshot Qdrant (SHA-256)
│   ├── restore.py                 # Restaurare din backup cu verificare SHA-256
│   └── authorize_google_calendar.py
│
├── src/
│   └── app/                       # Codul sursă Python
│       ├── main.py                # Punctul de intrare FastAPI & Healthchecks
│       ├── api/                   # Rute HTTP (Telegram, Automation, Health)
│       ├── core/                  # Configurații (.env), Securitate, Logging, Retry
│       ├── orchestrator/          # AI Orchestrator & Tool Registry
│       ├── agents/                # Agenți specializați (Email, Calendar, News, Practice)
│       ├── llm/                   # Abstracție LLM cu Ollama Fallback automat
│       ├── integrations/          # Conectori externi (Telegram, Google, IMAP/SMTP)
│       ├── rag/                   # Chunking, Ingestion, Embeddings, Retrieval
│       ├── memory/                # Memorie conversațională și Action Items
│       ├── database/              # Modele SQLAlchemy și Repositories
│       └── services/              # Generare Documente (.docx), Email, News
│
├── database/                      # Migrații Alembic și scripturi de seed
├── knowledge_base/                # Documente RAG pe ani universitari
│   ├── 2024-2025/
│   ├── 2025-2026/
│   └── 2026-2027/
├── docs/                          # Documentație tehnică detaliată (arhitectură, ghid, securitate, comparație LLM)
└── tests/                         # Teste Unitare (120 teste 100% verzi)
```

---

## 🚀 Ghid Rapid de Instalare (Development)

### Cerințe Preliminare
- Python 3.14
- Docker Desktop & Docker Compose
- Git

### 1. Clonare repository și creare mediu virtual

```powershell
git clone https://github.com/user/ai_assistant_try1.git
cd ai_assistant_try1
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Instalare dependențe

```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configurare Mediu (`.env`)

Copiați fișierul de exemplu și completați cheile API și credențialele:

```powershell
Copy-Item .env.example .env
```

### 4. Pornire infrastructură locală prin Docker Compose

```powershell
docker compose up -d postgres qdrant n8n ollama
docker compose run --rm ollama-init
docker compose --profile tools run --rm migrate
docker compose up -d --build app
```

### 5. Ingestie Knowledge Base Practică

```powershell
python -m src.app.rag.ingest
```

### 6. Verificare backend FastAPI

```powershell
Invoke-RestMethod http://localhost:8000/health/ready
```

Endpoint-uri utile:
- Swagger Docs: `http://localhost:8000/docs`
- Health Liveness: `http://localhost:8000/health/live`
- Health Readiness: `http://localhost:8000/health/ready`
- Dependencies Audit: `http://localhost:8000/health/dependencies`

---

## ⚡ Automatizări & Notificări Proactive (CLI & n8n)

Sistemul include un utilitar unificat de execuție a joburilor de automatizare (`scripts/run_automation.py`):

```powershell
# 1. Briefing matinal zilnic (Calendar + Sarcini + Top Știri) trimis pe Telegram:
python scripts/run_automation.py --job briefing

# 2. Verificarea termenelor limită de practică UNITBV și emitere alertă:
python scripts/run_automation.py --job deadlines

# 3. Refresh agregator știri tehnologice:
python scripts/run_automation.py --job news

# 4. Polling căsuțe de email (Personal & UNITBV) și alertă la mesaje urgente:
python scripts/run_automation.py --job email

# 5. Rulare backup complet (PostgreSQL + Qdrant) cu notificare Telegram:
python scripts/run_automation.py --job backup

# 6. Executare simultană a tuturor joburilor:
python scripts/run_automation.py --job all
```

---

## 🛡️ Backup & Disaster Recovery

Procedura este protejată prin validare criptografică:
- **Creare Backup:**
  ```powershell
  python -m scripts.backup --output-dir backups
  ```
  Generează `postgres.dump`, `qdrant.snapshot` și `manifest.json` cu sumele SHA-256.
- **Restaurare din Backup:**
  ```powershell
  python -m scripts.restore backups/<timestamp> --yes
  ```

---

## 🗓️ Roadmap Milestones

Toate etapele proiectului au fost implementate, testate și validate:

- [x] **M0: Analiză și Arhitectură** (Structură directoare, modele date, docs arhitectură, Docker Compose)
- [x] **M1: Infrastructură & Telegram MVP** (FastAPI, Docker, memorie conversațională PostgreSQL, webhook securizat)
- [x] **M2: Email Agent + UNITBV** (IMAP/SMTP dublu, extragere acțiuni/sarcini, clasificare mesaje)
- [x] **M3: Calendar + News Agent** (Google Calendar API v3 cu Service Account, agregator RSS cu ranking)
- [x] **M4: Practice Knowledge Base + RAG & Docx Generator** (Qdrant, nomic-embed-text, generare Convenție și Caiet .docx)
- [x] **M5: Tastaturi Interactive & Human-in-the-Loop** (Meniu persistent, butoane inline Approve/Reject/Complete)
- [x] **M6: Knowledge Base Multi-anual & Action Items** (Filtrare per an universitar, management sarcini)
- [x] **M7: Resilient LLM Runtime** (OpenAI/Gemini cloud cu fallback automat la nivel de provider pe Ollama local `qwen2.5:1.5b`)
- [x] **M8: Automatizări Proactive, n8n & Backup Disaster Recovery** (Briefing matinal, alerte termene, dump PostgreSQL + snapshot Qdrant SHA-256)
- [x] **M9: Final Delivery & Packaging** (120/120 teste unitare și de integrare 100% verzi, documentație tehnică completă, comparație Cloud vs Local LLM)

---

## 🛡️ Securitate și Confidențialitate

- **Fără chei hardcodate**: Toate credențialele sunt stocate în fișierul `.env` (exclus din Git).
- **Human Approval**: Orice acțiune cu efect extern (trimitere e-mail, modificare calendar) necesită confirmare directă din Telegram prin butoane inline.
- **Strict Data Isolation**: Informațiile sensibile și fișierele de practică sunt stocate exclusiv în instanțele locale ale bazei de date.
- **Criptografie SHA-256**: Orice restaurare din backup verifică integritatea fișierelor înainte de aplicare.
