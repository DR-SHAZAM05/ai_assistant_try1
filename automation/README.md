# Modulul de Automatizare Programată (n8n Workflows)

Acest director conține fluxurile de lucru automate definite pentru motorul de orchestrare **n8n** integrat în stiva Docker a proiectului `Personal Academic AI Assistant`.

---

## 1. Accesare Interfață n8n
- **URL n8n Web UI**: [http://localhost:5678](http://localhost:5678)
- Container: `academic_ai_n8n`
- Rețea Docker internă: `assistant_net`
- Hostname aplicație FastAPI în rețea: `http://academic_ai_app:8000`

---

## 2. Autentificare & Chei Secrete
Toate endpoint-urile interne de automatizare din `/api/v1/automation/*` sunt protejate criptografic prin header-ul HTTP:
```http
X-Automation-Key: {{ $env.AUTOMATION_API_KEY }}
```
Variabila `AUTOMATION_API_KEY` este injectată automat în containerele `academic_ai_app` și `academic_ai_n8n` din fișierul `.env`.

---

## 3. Fluxuri Disponibile în `automation/workflows/`

| Fișier Workflow | Declanșator (Trigger) | Endpoint Apelat | Descriere |
| :--- | :--- | :--- | :--- |
| `daily_news_refresh.json` | În fiecare dimineață la **08:00** | `POST /api/v1/automation/news/refresh` | Descarcă fluxurile RSS tehnologice/academice, deduplică prin SHA-256 și recalculează scorurile de relevanță. |
| `daily_email_poll.json` | Periodic la fiecare **2 ore** | `POST /api/v1/automation/email/poll` | Verifică starea cutiilor poștale (personal și @student.unitbv.ro) în mod read-only fără costuri LLM. |
| `practice_deadline_reminder.json` | Zilnic la **09:30** | `POST /api/v1/automation/practice/deadlines-check` | Monitorizează sarcinile active și termenele de practică, trimițând notificări push pe Telegram. |

---

## 4. Importul unui Workflow în n8n

1. Deschide [http://localhost:5678](http://localhost:5678) în browser.
2. În panoul din stânga, apasă pe **Workflows** -> butonul **Add Workflow** (sau meniul cu trei puncte `...`).
3. Selectează **Import from File...** și alege fișierul JSON dorit din `automation/workflows/`.
4. Verifică nodurile conectate și apasă pe comutatorul **Active** din colțul din dreapta sus pentru a porni execuția programată.
