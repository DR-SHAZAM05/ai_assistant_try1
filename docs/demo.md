# Personal Academic AI Assistant – Demo & Verification Guide

Acest ghid oferă instrucțiuni pas-cu-pas pentru testarea și demonstrarea tuturor funcționalităților asistentului academic (M0–M9).

> RSS, Qdrant și Ollama pot fi validate local cu Docker. Calendar, IMAP/SMTP și Telegram necesită `.env` complet și credențiale valide. Cu `ALLOW_MOCK_PROVIDERS=true`, development poate folosi fixture-uri locale; acesta nu este un test de acceptanță pentru un cont extern real.

---

## 1. Pornirea Sistemului (Quickstart)

```bash
# 1. Copiază fișierul de configurare
cp .env.example .env

# 2. Pornește dependențele persistente și Ollama
docker compose up -d postgres qdrant n8n ollama
docker compose run --rm ollama-init
docker compose --profile tools run --rm migrate

# 3. Pornește FastAPI numai după bootstrap și migrări
docker compose up -d --build app

# 4. Activează mediul virtual Python 3.14 și instalează dependențele
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1    # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt

# 5. Ingestează Knowledge Base-ul de practică (multi-anual: 2024-2025, 2025-2026, 2026-2027)
python -m src.app.rag.ingest

# 6. Verifică aplicația deja pornită în Docker
curl http://localhost:8000/health/ready
```

---

## 2. Scenariu Demonstrativ Oficial Complet (End-to-End Demo – Secțiunea 32)

Acest scenariu parcurge cap-coadă fluxul demonstrativ oficial definit în cerințele proiectului, arătând sinergia dintre agenți, menținerea contextului conversațional, agregarea de date și mecanismele Human-in-the-Loop.

| Pas | Rol | Mesaj / Acțiune | Răspuns Asistent / Comportament Sistem |
|---|---|---|---|
| **1** | Student | `Ce am azi în calendar?` | Interoghează Google Calendar API prin `CalendarAgent`. |
| **2** | Asistent | `Evenimentele de azi:`<br>1. 10:00 - Curs Sisteme Inteligente<br>2. 14:00 - Ședință practică FIESC<br>3. 16:30 - Consultații laborator | Listează ordonat cronologic evenimentele găsite în calendar. |
| **3** | Student | `Și după al doilea?` | Memoria conversațională (`ConversationMemory`) detectează referința anafalică. |
| **4** | Asistent | `După al doilea eveniment (Ședință practică FIESC, ora 14:00), ai în program: 16:30 - Consultații laborator.` | Identifică al doilea eveniment din contextul anterior și extrage următorul eveniment. |
| **5** | Asistent | `⚠️ Alertă E-mail UNITBV: A sosit un nou mesaj important referitor la practică de la secretariat@unitbv.ro!` | Notificare proactivă recepționată prin webhook sau polling automat. |
| **6** | Student | `Fă un rezumat și spune-mi ce am de făcut.` | `EmailAgent` analizează conținutul și extrage acțiunile necesare. |
| **7** | Asistent | `Rezumat: Se solicită transmiterea adeverinței de practică semnate și a caietului completat. Termenul limită este 28 august 2026. Acțiuni: (1) Verifică semnătura tutorelui; (2) Trimite documentele scanate.` | Extrage cerința și termenul limită din corpul mesajului. |
| **8** | Student | `Pregătește un draft de răspuns.` | `EmailAgent` sintetizează un draft oficial în stil academic. |
| **9** | Asistent | `Am pregătit draftul următor:\n„Bună ziua,\nVă confirm primirea mesajului. Am finalizat stagiul de 90 de ore și voi transmite caietul și adeverința semnate până la 28 august 2026.\nCu stimă,\nStudent”\n\nDorești să trimit acest e-mail acum?\n[ ✉️ Trimite ]   [ ❌ Anulează ]` | Draftul este marcat `pending_approval`. Trimiterea este blocată până la confirmare explicită (*Human-in-the-Loop*). |
| **10** | Student | `Cum am procedat anul trecut cu adeverința?` | `PracticeAgent` detectează intenția `PRACTICE_HISTORY_QUERY` și interoghează baza istorică (anul `2025-2026` / `2024-2025`). |
| **11** | Asistent | `Anul trecut (2025-2026), conform istoricului salvat, adeverința de practică a fost descărcată în format tipizat, semnată de tutorele companiei și trimisă scanată pe adresa secretariatului înainte de colocviu. (Sursa: [2025-2026] Ghid_Practica_2025_2026.md)` | Răspunde exact pe baza RAG și a istoricului din anul universitar anterior, citând sursele. |

---

## 3. Scenarii Individuale de Testare E2E (cURL & Telegram Webhook)

### Scenariul 1: Întrebare despre Practică (RAG An Curent 2026-2027)
```bash
curl -X POST "http://localhost:8000/api/v1/telegram/webhook" \
  -H "Content-Type: application/json" \
  -d '{
    "update_id": 1001,
    "message": {
      "message_id": 1,
      "date": 1700000000,
      "chat": {"id": 123456, "type": "private"},
      "from": {"id": 123456, "is_bot": false, "first_name": "Student"},
      "text": "Cum se face practica și ce documente sunt necesare?"
    }
  }'
```
**Rezultat așteptat**: Răspuns sintetizat din `Ghid_Practica_2026_2027.md` cu lista documentelor (convenție, caiet, adeverință) și citarea sursei `[2026-2027]`.

---

### Scenariul 2: Întrebare Multi-anuală / An Anterior (M6)
```bash
curl -X POST "http://localhost:8000/api/v1/telegram/webhook" \
  -H "Content-Type: application/json" \
  -d '{
    "update_id": 1002,
    "message": {
      "message_id": 2,
      "date": 1700000000,
      "chat": {"id": 123456, "type": "private"},
      "from": {"id": 123456, "is_bot": false, "first_name": "Student"},
      "text": "Care a fost termenul pentru depunerea convenției în 2024-2025?"
    }
  }'
```
**Rezultat așteptat**: Căutare filtrată exclusiv pe anul universitar `2024-2025` cu extragerea datei de 15 iulie 2025.

---

### Scenariul 3: Generare Draft E-mail UNITBV + Human Approval (M5)
```bash
# 1. Solicită generare draft
curl -X POST "http://localhost:8000/api/v1/telegram/webhook" \
  -H "Content-Type: application/json" \
  -d '{
    "update_id": 1003,
    "message": {
      "message_id": 3,
      "date": 1700000000,
      "chat": {"id": 123456, "type": "private"},
      "from": {"id": 123456, "is_bot": false, "first_name": "Student"},
      "text": "Răspunde la mailul de practică de pe UNITBV folosind ghidul oficial."
    }
  }'

# 2. Aprobare trimitere
curl -X POST "http://localhost:8000/api/v1/telegram/webhook" \
  -H "Content-Type: application/json" \
  -d '{
    "update_id": 1004,
    "message": {
      "message_id": 4,
      "date": 1700000000,
      "chat": {"id": 123456, "type": "private"},
      "from": {"id": 123456, "is_bot": false, "first_name": "Student"},
      "text": "Da."
    }
  }'
```
**Rezultat așteptat**: Pasul 1 generează draftul pe baza ghidului RAG; Pasul 2 trimite e-mailul și salvează rezumatul Q/A în baza de date `practice_questions`/`practice_answers`.

---

### Scenariul 4: Calendar & Știri (M3)
```bash
# Interogare Google Calendar
curl -X POST "http://localhost:8000/api/v1/telegram/webhook" \
  -H "Content-Type: application/json" \
  -d '{
    "update_id": 1005,
    "message": {
      "message_id": 5,
      "date": 1700000000,
      "chat": {"id": 123456, "type": "private"},
      "from": {"id": 123456, "is_bot": false, "first_name": "Student"},
      "text": "Ce evenimente am în calendar mâine?"
    }
  }'

# Interogare Știri AI / UNITBV
curl -X POST "http://localhost:8000/api/v1/telegram/webhook" \
  -H "Content-Type: application/json" \
  -d '{
    "update_id": 1006,
    "message": {
      "message_id": 6,
      "date": 1700000000,
      "chat": {"id": 123456, "type": "private"},
      "from": {"id": 123456, "is_bot": false, "first_name": "Student"},
      "text": "Ce știri noi sunt despre inteligența artificială?"
    }
  }'
```

---

### Scenariul 5: Generare Automată Documente de Practică (.docx)
```bash
curl -X POST "http://localhost:8000/api/v1/telegram/webhook" \
  -H "Content-Type: application/json" \
  -d '{
    "update_id": 1007,
    "message": {
      "message_id": 7,
      "date": 1700000000,
      "chat": {"id": 123456, "type": "private"},
      "from": {"id": 123456, "is_bot": false, "first_name": "Student"},
      "text": "Generează-mi caietul de practică și convenția cadru"
    }
  }'
```
**Rezultat așteptat**: Asistentul compilează prin `DocumentGeneratorService` fișierele `.docx` complete, le atașează prin `sendDocument` pe Telegram și le livrează direct utilizatorului, alături de instrucțiunile de completare.

---

### Scenariul 6: Butoane Interactive Inline & Human-in-the-Loop
```bash
# Apăsare pe butonul inline de aprobare trimitere draft email:
curl -X POST "http://localhost:8000/api/v1/telegram/webhook" \
  -H "Content-Type: application/json" \
  -d '{
    "update_id": 1008,
    "callback_query": {
      "id": "cb_001",
      "from": {"id": 123456, "is_bot": false, "first_name": "Student"},
      "message": {"message_id": 8, "chat": {"id": 123456, "type": "private"}},
      "data": "approve_draft:1"
    }
  }'
```
**Rezultat așteptat**: Webhook-ul validează interacțiunea, trimite emailul aprobat și returnează confirmarea acțiunii direct în chat.

---

### Scenariul 7: Notificări Proactive & Scheduled Daily Briefing (CLI & n8n)
```powershell
# 1. Declanșare Briefing Matinal complet (Calendar + Sarcini + Știri):
python scripts/run_automation.py --job briefing

# 2. Verificare jaloane și termene limită de practică UNITBV:
python scripts/run_automation.py --job deadlines
```
**Rezultat așteptat**: Utilizatorul primește mesaj push structurat pe Telegram conținând orarul zilei, task-urile academice nerezolvate și proximitatea colocviului de practică.

---

### Scenariul 8: Backup Criptografic & Disaster Recovery (SHA-256)
```powershell
# 1. Creare backup complet (PostgreSQL + Qdrant) cu trimitere alertă Telegram:
python scripts/run_automation.py --job backup

# 2. Verificare integritate și restaurare din backup:
python -m scripts.restore backups/20260910T161528Z --yes
```
**Rezultat așteptat**: Validarea checksum-urilor SHA-256 din `manifest.json`, restaurarea tabelelor din baza de date și a snapshot-ului vectorial.

---

### Scenariul 9: Fallback Rezilient la LLM Local Ollama (Zero Downtime)
```powershell
# Testare directă a providerului în condiții de simulare Rate Limit / Quota Exceeded:
docker exec academic_ai_app python -c "import asyncio; from src.app.llm.openai_provider import OpenAIProvider; p = OpenAIProvider(); print(asyncio.run(p.generate_completion('Salut!')))"
```
**Rezultat așteptat**: La detectarea `429 RateLimitError` pe endpoint-ul cloud, `OpenAIProvider` comută automat pe containerul Docker `academic_ai_ollama` (`qwen2.5:1.5b`) și oferă răspunsul fără eroare.

---

## 4. Rularea Testelor Automate

Pentru a rula întreaga suită de teste (peste 125 de teste 100% verzi):
```powershell
# Rulare în interiorul containerului Docker:
docker exec -e PYTHONPATH=. academic_ai_app pytest -v

# Sau pe mașina host în mediul virtual:
$env:PYTHONPATH="."
.\.venv\Scripts\pytest.exe tests/ -v
```
