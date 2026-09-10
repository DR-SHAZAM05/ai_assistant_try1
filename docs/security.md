# Politici și Mecanisme de Securitate

## 1. Protecția Credențialelor
- Fișierele de mediu (`.env`, `credentials.json`, `token.json`) sunt excluse strict din Git prin `.gitignore`.
- Credențialele pentru OAuth, IMAP, SMTP și API keys sunt încărcate doar la runtime prin `pydantic-settings`.
- Cheile OpenAI, token-ul Telegram, parolele de email, URL-urile cu credențiale pentru PostgreSQL și orice `QDRANT_API_KEY` trebuie păstrate doar în `.env` sau secret manager-ul mediului de deploy.
- Fișierele din `secrets/`, inclusiv tokenul OAuth Google Calendar și cheia service-account, sunt excluse din Git.
- `.env.example` trebuie să conțină numai placeholders, niciodată credentiale reale.
- `.dockerignore` exclude `.env`, `secrets/`, medii virtuale, backup-uri și chei din contextul trimis la Docker daemon.

## 2. Human-in-the-Loop (Aprobare Umană)
- Trimiterea e-mailurilor este blocată până când utilizatorul confirmă explicit draftul pe Telegram cu `Da` sau îl anulează cu `Nu`.
- Variabila `REQUIRE_HUMAN_APPROVAL_FOR_EMAILS=true` forțează generarea doar de draft-uri până la confirmare.
- Drafturile au proprietar Telegram, expirare configurabilă și sunt trecute atomic în starea `approved` înainte de SMTP. Nu există fallback la „ultimul draft” global.

## 3. Audit Logging
- Evenimentele de orchestrare sunt scrise în tabela `audit_logs` din PostgreSQL după rularea migrațiilor Alembic.
- În development/test, dacă PostgreSQL este oprit, auditul poate folosi memorie de proces. În producție (`ALLOW_MOCK_PROVIDERS=false`), indisponibilitatea bazei de date este expusă ca eroare și nu ca persistare reușită.
- Nu sunt salvate corpuri integrale de e-mailuri sau informații sensibile personale în log-urile de audit.
- `AUDIT_LOG_STORE_REQUEST_CONTENT=false` este valoarea sigură implicită; logging-ul redacționează tokenuri și parole chiar dacă un apelant le trimite accidental.
- `SQL_ECHO=false` este valoarea sigură implicită; nu activa SQL echo într-un deployment care poate procesa date personale.

## 4. Rate limiting și webhook-uri
- Webhook-ul Telegram aplică o fereastră glisantă per utilizator, configurată prin `TELEGRAM_RATE_LIMIT_REQUESTS` și `RATE_LIMIT_WINDOW_SECONDS`, și răspunde cu `429` plus `Retry-After` când limita este depășită.
- Implementarea este în memorie și este corectă pentru un singur proces FastAPI. Pentru mai multe replici, mută limitarea într-un backend partajat (de exemplu Redis) înainte de scalare orizontală.
- Configurarea webhook-ului cere întotdeauna secretul configurat și acceptă exclusiv URL-uri HTTPS publice.

## 5. Practice Knowledge Base & RAG
- Documentele din `knowledge_base/` pot conține informații academice sau date despre studenți. Nu loga conținutul complet al documentelor, întrebărilor sensibile sau răspunsurilor generate.
- Ingestion-ul salvează în PostgreSQL doar metadata necesară pentru trasabilitate: nume fișier, cale locală, an universitar, checksum, status și număr de chunks/vectori.
- Qdrant stochează payload-ul chunk-urilor pentru retrieval. Accesul la Qdrant trebuie limitat la rețeaua aplicației sau protejat prin `QDRANT_API_KEY` când este expus în afara hostului local.
- `RAG_SCORE_THRESHOLD` este folosit ca protecție anti-hallucination: dacă nu există context relevant, Practice Agent returnează un mesaj de informație insuficientă în loc să inventeze.
- Promptul Practice Agent cere explicit răspuns exclusiv din contextul furnizat și interzice completarea din cunoștințe generale.

## 6. PostgreSQL și Qdrant în Docker
- În Docker Compose, aplicația folosește `QDRANT_URL=http://qdrant:6333`; `localhost` din container ar indica aplicația însăși, nu serviciul Qdrant.
- Volumele `postgres_data` și `qdrant_storage` conțin date persistente și trebuie protejate la backup/restore.
- Nu publica porturile PostgreSQL/Qdrant pe internet fără autentificare, firewall și rotație de credentiale.
- Compose leagă toate porturile la `127.0.0.1` implicit. Endpointurile n8n pentru polling cer `AUTOMATION_API_KEY`; nu activa workflow-uri până când cheia nu este configurată.
