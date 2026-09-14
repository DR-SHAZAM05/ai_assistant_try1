# Personal Academic AI Assistant

Asistent AI modular dezvoltat pentru mediul academic (studenți și cadre didactice UNITBV), capabil să interacționeze printr-o interfață conversațională de Telegram cu e-mailul personal, e-mailul instituțional UNITBV, Google Calendar, surse configurabile de știri și o bază de cunoștințe de practică structurată pe ani universitari.

---

## Caracteristici Principale

- **Interfață conversațională Telegram**: Comunicare în limbaj natural, meniu de comenzi rapide și butoane inline pentru acțiuni directe (`[Răspunde]`, `[Trimite]`, `[Anulează]`, `[Finalizează #ID]`).
- **AI Orchestrator Central**: Rutare automată a intențiilor și coordonare multi-agent (Email, Calendar, Practică, Știri, Sarcini, Generare Documente).
- **Generare documente oficiale (.docx)**: Generare automată și transmitere direct în chat-ul de Telegram a Convenției-cadru și a Caietului de practică structurat pe 3 săptămâni.
- **Suport cont dublu de e-mail**: Conectare simultană la contul personal și cel instituțional (`@student.unitbv.ro` / `@unitbv.ro`), clasificare automată a mesajelor și extragere de acțiuni/deadline-uri.
- **Modul dedicat pentru practica UNITBV**: Identificare automată a mesajelor referitoare la practică (convenții, caiete, adeverințe, colocviu, Erasmus) și salvarea rezumatelor în istoricul deciziilor.
- **Knowledge Base & RAG multi-anual**: Căutare semantică în regulamente și ghiduri organizate pe ani universitari (2024-2025, 2025-2026, 2026-2027) și într-o secțiune generală stabilă pentru regulamente permanente.
- **Integrare Google Calendar**: Consultare orar, identificare eveniment următor, verificare intervale orare libere/ocupate și programare evenimente prin Google Calendar API v3.
- **Calendar – Human-in-the-Loop**: Creare, modificare și ștergere de evenimente cu ciclu complet: cerere → preview → confirmare/anulare → executare → audit.
- **Agregator de știri tehnologice**: Preluare surse RSS definite în `config/news.yaml`, deduplicare articole și calcul al scorului de relevanță pentru topicuri IT și AI.
- **Human-in-the-Loop**: Confirmare obligatorie a utilizatorului din Telegram înainte de trimiterea oricărui e-mail sau modificare în calendar.
- **Provider LLM hibrid**: Execuție primară prin cloud (Gemini / OpenAI), cu comutare automată pe runtime-ul local Ollama (`qwen2.5:1.5b`) în caz de erori de conexiune sau depășire a cotelor de utilizare.
- **Automatizări și notificări**: Fluxuri n8n și utilitar CLI (`scripts/run_automation.py`) pentru briefing matinal pe 5 secțiuni, monitorizare termene limită și alertare e-mailuri urgente.
- **Disaster Recovery și backup**: Salvarea bazei de date PostgreSQL și a snapshot-ului vectorial Qdrant cu verificare criptografică SHA-256.

---

## Arhitectură Generală

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
| - Mesaje & Memorie Conversațională  |  | - Embeddings Ghid Practică UNITBV |
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

## Structura Proiectului

```text
personal-academic-ai-assistant/
│
├── README.md                      # Documentație principală a proiectului
├── .env.example                   # Șablon configurare variabile de mediu
├── .gitignore                     # Reguli ignorare Git
├── .dockerignore                  # Excluderi context build Docker
├── Dockerfile                     # Configurație build pentru backend FastAPI
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
├── config/                        # Fișiere de configurare dinamice
│   ├── news.yaml
│   ├── news.example.yaml
│   ├── practice.yaml
│   └── practice.example.yaml
│
├── scripts/                       # Instrumente de operare și automatizare
│   ├── run_automation.py          # Utilitar CLI unificat pentru joburi automate
│   ├── backup.py                  # Salvare PostgreSQL + Snapshot Qdrant (SHA-256)
│   ├── restore.py                 # Restaurare date cu verificare de integritate
│   └── authorize_google_calendar.py
│
├── src/
│   └── app/                       # Codul sursă al aplicației
│       ├── main.py                # Inițializare FastAPI și endpoint-uri de sănătate
│       ├── api/                   # Rute HTTP (Telegram webhook, automatizări, health)
│       ├── core/                  # Configurații (.env), securitate, logging
│       ├── orchestrator/          # Detecție intenții și coordonare unelte
│       ├── agents/                # Agenți specializați (Email, Calendar, News, Practice)
│       ├── llm/                   # Abstracție LLM cu mecanism de fallback pe Ollama
│       ├── integrations/          # Conectori externi (Telegram, Google, IMAP/SMTP)
│       ├── rag/                   # Chunking, embeddings, vector store Qdrant, retrieval
│       ├── memory/                # Memorie conversațională și persistență sarcini
│       ├── database/              # Modele SQLAlchemy și sesiune asincronă
│       └── services/              # Servicii de business logic (Docx, Email, News, Calendar)
│
├── database/                      # Migrații de schemă Alembic
├── knowledge_base/                # Ghiduri de practică pe ani și regulament cadru
│   ├── 2024-2025/
│   ├── 2025-2026/
│   ├── 2026-2027/
│   └── general/
├── docs/                          # Documentație tehnică (arhitectură, demo, comparație LLM)
└── tests/                         # Suită completă de teste unitare și de integrare
```

---

## Ghid de Instalare și Pornire

### Cerințe Preliminare
- Python 3.14
- Docker Desktop și Docker Compose
- Git

### 1. Clonare repository și configurare mediu virtual

```powershell
git clone https://github.com/user/ai_assistant_try1.git
cd ai_assistant_try1

py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1   # Pe Linux/Mac: source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Configurare variabile de mediu (`.env`)

Copiați fișierul de exemplu și completați valorile specifice:

```powershell
Copy-Item .env.example .env    # Pe Linux/Mac: cp .env.example .env
```

Parametri esențiali:
- `TELEGRAM_BOT_TOKEN`: token eliberat de `@BotFather`
- `OPENAI_API_KEY`: cheie API OpenAI sau Gemini
- Credențiale cont personal și cont instituțional UNITBV (IMAP/SMTP)
- Pentru dezvoltare locală fără servicii externe active, setarea `ALLOW_MOCK_PROVIDERS=true` permite rularea pe date simulate locale.

### 3. Pornire infrastructură cu Docker Compose

```powershell
# 1. Pornire servicii suport (PostgreSQL, Qdrant, n8n, Ollama)
docker compose up -d postgres qdrant n8n ollama

# 2. Descărcare model embeddings și model local în Ollama
docker compose run --rm ollama-init

# 3. Rulare migrații de bază de date
docker compose --profile tools run --rm migrate

# 4. Pornire aplicație backend
docker compose up -d --build app
```

### 4. Ingestia documentelor de practică în Qdrant

```powershell
python -m src.app.rag.ingest
```

### 5. Verificare stare aplicație

Puteți verifica endpoint-ul de readiness:

```powershell
Invoke-RestMethod http://localhost:8000/health/ready
```

Răspunsul așteptat este `{"status":"ready"}`.

Endpoint-uri utile:
- Documentație Swagger: `http://localhost:8000/docs`
- Verificare Liveness: `http://localhost:8000/health/live`
- Verificare Readiness: `http://localhost:8000/health/ready`
- Audit dependințe: `http://localhost:8000/health/dependencies`
- Panou n8n: `http://localhost:5678`

---

## Calendar – Human-in-the-Loop

Fluxul obligatoriu pentru orice operație de creare, modificare sau ștergere a evenimentelor din calendar:

```
Request
  ↓
Pending Action (BD)
  ↓
Preview (Utilizator)
  ↓
Confirmă / Anulează
  ↓
Provider (dacă confirmat)
  ↓
Audit
```

**Butoane Telegram**:
```
Confirmă
Anulează
```

**Caracteristici de securitate**:
- User isolation: utilizatorul nu poate confirma/anula acțiunile altor utilizatori
- Double-confirm protection: aceeași acțiune nu poate fi executată de două ori
- TTL: acțiunile expiră după 15 minute (configurable: `CALENDAR_ACTION_TTL_SECONDS`)
- Audit sanitisation: redactare automată a e-mailurilor, numerelor de telefon, tokenurilor din audit
- Timezone awareness: `Europe/Bucharest` pentru date relative (azi, mâine, săptămâna viitoare)

---

## Automatizări și Joburi Programate (`scripts/run_automation.py`)

Utilitarul CLI unificat permite execuția manuală sau programată prin Task Scheduler / cron a fluxurilor:

```powershell
# Briefing matinal complet (Calendar, Email, Practică UNITBV, Sarcini, Știri):
python scripts/run_automation.py --job briefing

# Verificare termene limită practică (28 august, 2 septembrie) și emitere alertă:
python scripts/run_automation.py --job deadlines

# Actualizare fluxuri de știri tehnologice:
python scripts/run_automation.py --job news

# Verificare căsuțe e-mail pentru mesaje urgente:
python scripts/run_automation.py --job email

# Backup complet PostgreSQL și Qdrant:
python scripts/run_automation.py --job backup

# Rulare simultană a tuturor joburilor:
python scripts/run_automation.py --job all
```

---

## Backup și Disaster Recovery

Procedura include verificarea integrității datelor prin sume de control:

- **Creare Backup**:
  ```powershell
  python -m scripts.backup --output-dir backups
  ```
  Generează `postgres.dump`, `qdrant.snapshot` și `manifest.json` cu sumele SHA-256.

- **Restaurare din Backup**:
  ```powershell
  python -m scripts.restore backups/<timestamp> --yes
  ```

---

## Securitate și Izolare

- **Gestionare credențiale**: Nu există chei sau parole hardcodate în codul sursă; configurarea se realizează exclusiv prin variabile de mediu `.env` excluse din Git.
- **Mecanism Human-in-the-Loop**: Orice acțiune cu impact extern (trimitere e-mail sau modificare în calendar) este oprită în starea `pending_approval` până la confirmarea explicită prin butoane inline în Telegram.
- **Izolare date**: Baza relațională și vector store-ul rulează în rețeaua Docker internă, nefiind expuse public în mod direct.
- **Integritate SHA-256**: Procedura de restaurare validează sumele fiecărui fișier înainte de aplicarea modificărilor.

---

## Testare Automată

Aplicația dispune de o suită completă de teste unitare și de integrare, acoperind toate fluxurile principale și cerințele specifice de testare (T1-T5):

```powershell
# Rulare în interiorul containerului Docker:
docker exec -e PYTHONPATH=. academic_ai_app pytest -v

# Rulare pe mașina gazdă:
pytest -v
```

> Suita curentă: **129 teste trecute cu succes (100% verzi)**.
