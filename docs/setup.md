# Setup and Deployment

## Prerequisites

- CPython 3.14 for local development and containers. Python 3.10 is no longer a supported runtime.
- Docker Desktop with the daemon running for PostgreSQL, Qdrant, and production-like tests.
- Optional: `pg_dump` and `pg_restore` on `PATH` for backup scripts. On Windows, the scripts automatically fall back to the running PostgreSQL Docker container.

## Development Setup

```powershell
Copy-Item .env.example .env
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
docker compose up -d postgres qdrant n8n ollama
docker compose run --rm ollama-init
docker compose --profile tools run --rm migrate
docker compose up -d --build app
python -m src.app.rag.ingest
```

The application reports liveness at `GET /health/live`, verifies PostgreSQL, Qdrant, and the active Ollama models at `GET /health/ready`, and exposes credential-free integration configuration plus local Ollama runtime state at `GET /health/dependencies`. A `503` response from readiness means a required persistent service is unavailable; liveness alone only proves that the process is running. Docker uses readiness for the application healthcheck.

The default command above starts the backend in Docker only after the model bootstrap and database migration complete. To develop the backend on the host instead, do not start the `app` service; start only its dependencies and bootstrap Ollama before launching Uvicorn:

```powershell
docker compose up -d postgres qdrant n8n ollama
docker compose run --rm ollama-init
uvicorn src.app.main:app --reload --port 8000
```

Inside Compose the app receives `POSTGRES_HOST=postgres` and `QDRANT_URL=http://qdrant:6333`; local shell execution uses the IPv4 loopback values in `.env`.

## Runtime Modes

`ALLOW_MOCK_PROVIDERS=true` is for development and tests only. It allows deterministic local providers when no credentials or service containers are available. In production set:

```env
APP_ENV=production
ALLOW_MOCK_PROVIDERS=false
SECRET_KEY=<at-least-32-random-characters>
CORS_ALLOWED_ORIGINS=https://assistant.example.edu
```

With `ALLOW_MOCK_PROVIDERS=false`, a configured provider failure is returned explicitly instead of becoming a simulated success. Run Alembic before starting the application; no runtime code creates database tables.

Keep `SQL_ECHO=false` outside of short-lived debugging sessions. It is intentionally off by default so SQL parameters and operational metadata do not land in container logs.

The Dockerfile, `.python-version`, `pyproject.toml`, and `requirements.txt` all target Python 3.14. Recreate a legacy Python 3.10 virtual environment instead of reusing it:

```powershell
Remove-Item -Recurse -Force .venv
py -3.14 -m venv .venv
```

Python dependencies and the Compose service images are version-pinned. The Dockerfile base image and Compose images are also pinned by digest; update a version and its digest together after validation.

## Windows and Docker Desktop

Docker Desktop must show **Engine running** and use the WSL 2 backend. The compose stack binds application, PostgreSQL, Qdrant, n8n, and Ollama ports to `127.0.0.1` by default. This is intended for a local Windows workstation. A public deployment should use a reverse proxy and explicitly set only `APP_BIND_ADDRESS=0.0.0.0`; keep database and Qdrant bind addresses on loopback or the internal Docker network.

If Ollama is already installed on Windows, it normally occupies `127.0.0.1:11434`. The Docker stack intentionally uses host port `11435` to avoid that collision; it remains port `11434` inside the Docker network. `docker compose up -d` starts `ollama-init`, which downloads the models named by `OLLAMA_INIT_CHAT_MODEL` and `OLLAMA_INIT_EMBEDDING_MODEL` into the persistent volume. The first run needs network access and may take several minutes; verify completion with `docker compose ps` and `docker compose logs ollama-init`. Compose supplies `OLLAMA_BASE_URL=http://ollama:11434` to the app, while local Python execution uses `http://127.0.0.1:11435`.

Validate the daemon before starting services:

```powershell
docker version
docker compose version
docker compose --env-file .env.example config --quiet
```

## Practice Knowledge Base and RAG

Place `.pdf`, `.txt`, and `.md` documents under `knowledge_base/<academic-year>/`, for example `knowledge_base/2026-2027/`, then run:

```powershell
python -m src.app.rag.ingest
```

The ingestion process records a checksum in PostgreSQL, skips unchanged files, removes vectors for changed files, and writes vectors to `QDRANT_COLLECTION`. The `academic_year` payload filter is applied to every practice retrieval.

Supported embedding modes are `openai`, `ollama`, and the development-only `mock`. The repository default is `nomic-embed-text` (768 dimensions) and uses `practice_knowledge_ollama_768` so it cannot conflict with legacy OpenAI collections at 1.536 dimensions. For an OpenAI deployment, select a separate collection matching the selected model's vector size before ingestion.

## Google Calendar

Set `CALENDAR_PROVIDER=google` and choose exactly one authorization mode:

- OAuth: set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, then run `python scripts/authorize_google_calendar.py`. The token is written to `GOOGLE_TOKEN_FILE` and is ignored by Git.
- Service account: set `GOOGLE_AUTH_MODE=service_account`, `GOOGLE_SERVICE_ACCOUNT_FILE`, and share the target calendar with the service-account email.

Calendar reads, creates, and deletes run through Google Calendar API v3. Calendar changes must still pass the human-approval workflow in the application.

## Email, Telegram, and News

- Configure IMAP/SMTP server, ports, TLS choices, folder, account, and app password for each email account. IMAP fetches retry bounded transient failures; SMTP sends do not retry automatically because a timeout may occur after the server accepted the message.
- The email list includes an `ID mesaj`. In production a draft must name that identifier (`Răspunde la e-mailul cu ID <...>`); the application never guesses the latest mailbox message.
- Set `TELEGRAM_BOT_TOKEN`, a random 32-256 character URL-safe `TELEGRAM_WEBHOOK_SECRET` (`A-Z`, `a-z`, `0-9`, `_`, `-`), a comma-separated `TELEGRAM_ALLOWED_USER_IDS` allow-list, and a public HTTPS `TELEGRAM_WEBHOOK_URL`. All four are mandatory when a Telegram bot is enabled in production; placeholder or weak values prevent startup. Register the webhook through `POST /api/v1/telegram/setup-webhook` only from an authenticated administrative path.
- RSS sources are configured under `news.sources` in `config/news.example.yaml`. They are fetched over HTTP at runtime; test data is injected only by tests.

## Automation CLI & Scheduled Jobs

All scheduled background operations can be executed via the unified zero-dependency CLI `scripts/run_automation.py`:

```powershell
# Run morning daily briefing (Calendar + Tasks + Top News) and push to Telegram:
python scripts/run_automation.py --job briefing

# Check academic practice milestone proximity (28 Aug, 2 Sept, 5-10 Sept):
python scripts/run_automation.py --job deadlines

# Poll inboxes for urgent messages:
python scripts/run_automation.py --job email

# Fetch and rank latest RSS news:
python scripts/run_automation.py --job news

# Trigger automated backup with Telegram push notification:
python scripts/run_automation.py --job backup

# Run all jobs in sequence:
python scripts/run_automation.py --job all
```

This CLI automatically reads `AUTOMATION_API_KEY` from `.env` and targets `http://127.0.0.1:8000` by default. It can be called from Windows Task Scheduler or Linux crontab.

## Practice Document Generation (.docx)

The system automatically generates official UNITBV academic documents in `.docx` format:
- **Convenție-cadru de colaborare pentru practică** (`conventie_cadru_practica`)
- **Caiet de practică FIESC** (`caiet_practica_fiesc`)

No local LibreOffice or Microsoft Word installation is needed; the files are compiled in-memory via `python-docx` and delivered directly as document attachments to Telegram.

## Resilient Hybrid LLM Provider

The application supports a resilient hybrid LLM setup:
- **Primary Provider**: Configured via `LLM_PROVIDER=openai` (or Google Gemini via its OpenAI-compatible endpoint).
- **Automatic Fallback**: If the cloud provider encounters network timeouts, connectivity failures, or HTTP 429 Quota Exceeded / Rate Limit errors, `OpenAIProvider` transparently fails over to the local Docker Ollama container (`qwen2.5:1.5b` on `http://ollama:11434`). This prevents Telegram webhook crashes and guarantees zero downtime.

## n8n Workflows

Set a high-entropy `AUTOMATION_API_KEY` in `.env`, start n8n, then import all JSON files from `automation/workflows/` (or `workflows/`) through its UI. The workflows call authenticated internal endpoints (`/api/v1/automation/...`); they are intentionally disabled until the key is set.

## Draft Approval Safety

Pending email drafts expire after `DRAFT_APPROVAL_TTL_SECONDS` (900 seconds by default), are persisted in PostgreSQL in production, and belong to exactly one Telegram user. A duplicate webhook or another user cannot approve the draft. In Telegram, the user can approve or reject directly using inline action buttons `[ ✉️ Trimite ]` / `[ ❌ Anulează ]`.

## Backup and Restore

With PostgreSQL client tools installed and services reachable:

```powershell
python -m scripts.backup --output-dir backups
python -m scripts.restore backups/<timestamp> --yes
```

The backup contains a PostgreSQL custom dump, a Qdrant collection snapshot, and a manifest. Restore deliberately requires `--yes` because it replaces current PostgreSQL data and the Qdrant collection snapshot.

When PostgreSQL client tools are not installed on Windows, the scripts automatically use `pg_dump` and `pg_restore` from `POSTGRES_DOCKER_CONTAINER`. Every v2 manifest contains SHA-256 checksums, verified before restore. For a non-destructive drill, restore into a separate existing database and collection:

```powershell
python -m scripts.restore backups/<timestamp> --yes --postgres-db academic_assistant_restore_validation --qdrant-collection backup_restore_validation
```

## Validation

```powershell
# In Docker:
docker exec -e PYTHONPATH=. academic_ai_app pytest -v

# On host:
$env:PYTHONPATH="."
python -m pytest tests -v
python -m alembic upgrade head --sql
docker compose --env-file .env.example config --quiet
```

When validating without creating `.env`, use `ENV_FILE=.env.example` as the Compose environment-file path (PowerShell: `$env:ENV_FILE='.env.example'`).

Live end-to-end validation additionally requires a running Docker daemon plus valid provider credentials. All 113 automated unit and integration tests are verified green.
