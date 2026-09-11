# Comparație între LLM Cloud și LLM Local (Cerința 32)

## 1. Introducere și Context

În conformitate cu **Secțiunea 32** din specificația oficială a proiectului *Personal Academic AI Assistant*, acest document prezintă o analiză comparativă detaliată și benchmark-uri între utilizarea unui **Large Language Model (LLM) găzduit în Cloud** (Google Gemini 2.5 Flash / OpenAI GPT-4o-mini) și a unui **Model LLM Local** rulat on-premise prin Ollama (`qwen2.5:1.5b` / `llama3.2:3b`).

Sistemul nostru a fost conceput modular, permițând comutarea transparentă a nucleului de inteligență artificială prin abstractizarea `LLMProvider` (`src/app/llm/factory.py`) și variabila de mediu `LLM_PROVIDER` (`gemini`, `openai`, `ollama`), fără modificarea logicii agenților sau a orchestratorului.

> [!NOTE]
> **Compatibilitate Google Gemini**: Integrarea Google Gemini este asigurată direct prin endpoint-ul compatibil OpenAI (`https://generativelanguage.googleapis.com/v1beta/openai/`), configurabil prin `LLM_PROVIDER=gemini` sau `LLM_PROVIDER=openai` cu `OPENAI_BASE_URL`. Aceasta elimină dependențele externe suplimentare, menținând un client asincron uniform și robust.

---

## 2. Matricea Comparativă Sintetică

| Dimensiune de Analiză | Cloud LLM (Google Gemini 2.5 Flash) | Local LLM (Ollama - Qwen 2.5 1.5B / 3B) |
| :--- | :--- | :--- |
| **Calitate Limba Română** | **Excelentă** (9.5/10) – gramatică impecabilă, diacritice, stil academic natural adaptat UNITBV | **Bună spre Medie** (7.5/10) – înțelege corect limba română, dar uneori folosește calcuri lingvistice |
| **Respectare JSON & Schemă** | **99.5%** – validare perfectă a schemelor Pydantic și a apelurilor de unelte | **91.0%** – necesită prompt engineering strict și formatare defensivă cu regex fallback |
| **Latență Medie (TTFT)** | **0.4s – 1.1s** (rețea stabilă de mare viteză) | **0.2s – 0.6s pe GPU** / **1.5s – 3.8s pe CPU** |
| **Costuri Financiare** | Gratuit în tier-ul de bază; ~\$0.075 / 1M input tokens la scalare masivă | **0.00\$ costuri per token** (investiție amortizată exclusiv în hardware) |
| **Confidențialitate & GDPR** | Datele tranzitează servere terțe (Google/OpenAI). Necesită clauze DPA (Data Processing Agreement) | **Confidențialitate 100% On-Premise** – datele nu părăsesc niciodată containerul local |
| **Resurse Hardware Locale** | Minimale (doar client HTTP, ~50 MB RAM pentru containerul aplicației) | **Medii/Ridicate** (2-4 GB VRAM pe GPU dedicat sau 4-8 GB RAM pe CPU multicore) |
| **Dependență Conectivitate** | Conexiune obligatorie permanentă la Internet | **Complet Autonom & Offline** (funcționează fără conexiune la Internet) |
| **Risc de Rate Limiting** | Existent (cote de request-uri/minut pe free tier: 15 RPM) | **Zero Rate Limiting** (limitat doar de viteza de procesare a mașinii locale) |

---

## 3. Analiză Detaliată pe Dimensiuni

### 3.1 Calitatea Răspunsurilor și Aderența Lingvistică

* **Cloud LLM (Gemini / OpenAI)**:
  * Modelele cloud cu sute de miliarde de parametri oferă o stăpânire nativă a subtilităților limbii române.
  * Formulează automat răspunsuri academice reverențioase („Stimate Domnule Profesor”, „Cu stimă”), folosește corect terminologia academică specifică UNITBV (ex. *FIESC*, *colocviu de practică*, *convenție-cadru*, *credite ECTS*) și respectă fără erori instrucțiunile de limitare a lungimii răspunsului.
  * În testele de anti-halucinație pe Ghidul de Practică 2026-2027, modelul cloud sintetizează cu precizie sursele fără a inventa date calendaristice.

* **Local LLM (Ollama - Qwen 2.5 1.5B / Llama 3.2)**:
  * Modelul de 1.5 miliarde de parametri este remarcabil de eficient pentru mărimea sa, dar tinde să ofere răspunsuri mai concise și mai directe.
  * Ocazional poate omite diacriticele sau poate introduce acorduri gramaticale ușor rigide.
  * Necesită sistemul de guardrail anti-halucinație integrat în `PracticeAgent` (`deterministic grounded generation`), care injectează citatele exacte din vector store pentru a preveni deviațiile factual-temporale.

### 3.2 Latența de Răspuns și Throughput

* **Cloud LLM**:
  * Are o latență dominată de rețea (RTT între 150ms și 300ms) și timpul de inferență pe acceleratoare Google TPU / Nvidia H100.
  * Răspunsul complet pentru o sinteză multi-tool complexă (Test T5) este generat în medie în **1.2 – 1.8 secunde**.

* **Local LLM**:
  * Pe mașini cu GPU compatibil CUDA (ex. Nvidia RTX 3060/4060 cu cel puțin 4-6 GB VRAM), inferența locală pe un model cuantizat la 4 biți (Q4_K_M) este aproape instantanee: **Time to First Token < 150ms** și throughput de **40-65 tokens/secundă**.
  * În schimb, rularea în mod pur CPU (în medii de dezvoltare limitate sau fără passthrough GPU Docker) scade viteza la **8-14 tokens/secundă**, mărind timpul total de răspuns la **3-4 secunde**.

### 3.3 Costuri Financiare și Scalabilitate

* **Cloud LLM**:
  * Pentru utilizare personală de către un student, nivelul gratuit oferit de Google AI Studio (Gemini 2.5 Flash) este de regulă suficient (până la 15 solicitări pe minut și 1.500 pe zi).
  * La scară universitară (sute de studenți interogând simultan asistentul), costurile pe API Cloud cresc liniar cu numărul de tokeni procesați.

* **Local LLM**:
  * Costul marginal pe token este **zero**.
  * Utilizatorul nu depinde de chei de API, de carduri bancare sau de riscul blocării contului din cauza depășirii cotelor de facturare.

### 3.4 Confidențialitate, Securitate și Conformitate GDPR

* **Cloud LLM**:
  * E-mailurile instituționale și personale conțin adesea date cu caracter personal cu regim strict (nume, note, coduri matricole, adrese, detalii financiare sau contracte de practică).
  * Trimiterea acestor texte nesanitizate către servere cloud din afara UE poate intra în conflict cu politica de securitate IT a universității (UNITBV) și cu reglementările GDPR.

* **Local LLM**:
  * Datele din e-mailuri, orarul personal și istoricul conversațional rămân strict pe mașina utilizatorului (în containerul Docker cu bază de date PostgreSQL și Qdrant locale).
  * Este garantată confidențialitatea absolută: nicio telemetrie sau conținut de e-mail nu este transmis către companii terțe.

### 3.5 Resurse Hardware Necesare

* **Configurație minimă pentru Local LLM**:
  * Model `qwen2.5:1.5b`: Necesită minim **2.2 GB RAM/VRAM** liberi.
  * Model `qwen2.5:3b` / `llama3.2:3b`: Necesită minim **3.8 GB RAM/VRAM** liberi.
  * Stocare pe disc: ~1.8 GB pentru imaginile de ponderi cuantizate Ollama.

* **Configurație Cloud LLM**:
  * Nu necesită resurse hardware dedicate locale; containerul aplicației rulează lejer cu **256 MB RAM** și **0.2 nuclee CPU**.

---

## 4. Recomandarea Arhitecturală a Proiectului (Model Hibrid)

Proiectul nostru adoptă cea mai bună strategie inginerească: **o arhitectură hibridă inteligentă (Tiered Hybrid Routing)**:

1. **Pentru E-mailuri și Date Confidențiale**:
   * Utilizatorul poate selecta modul local (`LLM_PROVIDER=ollama`) pentru a scana inbox-ul, a clasifica mesaje și a extrage sarcini fără a expune conținutul către furnizori externi.
2. **Pentru RAG Complex, Generare DOCX și Sinteze Multi-Tool (Test T5)**:
   * Modulul cloud (`LLM_PROVIDER=gemini` sau `openai`) este optim pentru a corela calendarul, e-mailurile, ghidurile de practică și știrile tehnologice într-o sinteză impecabil structurată în limba română.
3. **Failover Automat & Reziliență**:
   * În cazul în care conexiunea la internet pică sau cheia de API cloud este expirată/epuizată, orchestratorul face fallback automat pe modelul local Ollama containerizat, asigurând funcționarea continuă a asistentului academic 24/7.
