# Ghid de Utilizare – Personal Academic AI Assistant (UNITBV)

Acest ghid oferă instrucțiuni complete și exemple practice pentru utilizarea asistentului academic prin Telegram.

---

## 🚀 1. Pornire și Navigare Rapidă

Pentru a începe conversația sau pentru a reseta meniul principal, trimite comanda:
```text
/start
```
sau apasă pe comanda **/menu** din meniul Telegram.

### Meniul Rapid (Tastatură Persistentă)
Asistentul pune la dispoziție o tastatură permanentă în partea de jos a ecranului:
- `[ 📄 Practică UNITBV ]` – Ghidul oficial, regulamente, jaloane și descărcare documente Word (.docx).
- `[ 📅 Calendar & Orar ]` – Consultarea cursurilor, laboratoarelor și examenelor din Google Calendar.
- `[ 📋 Sarcini & Task-uri ]` – Lista de acțiuni academice și sarcini extrase automat din e-mailuri.
- `[ 📧 E-mail ]` – Verificarea căsuțelor de e-mail (Personal & UNITBV) și redactare răspunsuri.
- `[ 📰 Știri IT & AI ]` – Agregator de noutăți tehnologice relevante, filtrate și clasificate.

---

## 📄 2. Modulul de Practică Studențească & Documente Word

Asistentul este antrenat pe regulamentul oficial de practică al Facultății de Inginerie Electrică și Știința Calculatoarelor (FIESC) – Universitatea Transilvania din Brașov.

### Întrebări Frecvente (RAG Multi-anual)
Poți întreba orice detaliu în limbaj natural:
- *"Câte ore de practică trebuie să fac?"* → Asistentul răspunde: 90 de ore (pentru anul 2) sau conform anului de studiu.
- *"Când este colocviul de practică?"* → Asistentul indică perioada 5–10 septembrie.
- *"Ce documente trebuie să depun la finalul practicii?"* → Convenția-cadru, Caietul de practică și Adeverința de practică / Atestatul de la companie.
- *"Care a fost termenul în anul 2024-2025?"* → Căutare semantică în arhiva anilor anteriori.

### Generare & Descărcare Automată a Documentelor (.docx)
Poți solicita asistentului generarea documentelor oficiale gata de completat:
```text
Generează-mi caietul de practică și convenția cadru
```
sau
```text
Vreau convenția de practică în format Word
```
**Ce primești:**
Asistentul compilează documentele pe baza șabloanelor academice și le trimite **direct ca fișiere descărcabile `.docx` în conversația Telegram**:
1. `Conventie_Cadru_Practica_UNITBV.docx` – Convenția-cadru oficială de colaborare.
2. `Caiet_Practica_FIESC_UNITBV.docx` – Caietul de practică structurat pe săptămâni și tematici.

---

## 📅 3. Modulul Google Calendar & Orar

Asistentul citește în timp real evenimentele din Google Calendar prin Service Account sau OAuth:

### Exemple de Comenzi:
- *"Ce evenimente am mâine?"*
- *"Arată-mi programul pentru săptămâna viitoare"*
- *"Am vreun curs vineri dimineață?"*

Asistentul verifică evenimentele, îți prezintă intervalele orare și te avertizează dacă detectează suprapuneri (conflicte de orar).

---

## 📋 4. Managementul Sarcinilor & Action Items

Sarcinile pot fi create manual sau extrase automat din e-mailurile primite de la profesori.

### Exemple de Utilizare:
- **Vizualizare sarcini active:**
  *"Ce sarcini am de rezolvat?"*
  sau apasă pe `[ 📋 Sarcini & Task-uri ]`.

- **Adăugare sarcină nouă:**
  *"Adaugă sarcina: De finalizat referatul la Sisteme Încorporate până marți"*

- **Finalizare rapidă (One-Click):**
  Fiecare sarcină primită în lista de task-uri are asociat un buton inline `[ ✅ Finalizează #ID ]`. Apăsarea pe buton marchează sarcina instant ca finalizată în baza de date PostgreSQL.

---

## 📧 5. Modulul E-mail (Personal & UNITBV) și Human-in-the-Loop

Asistentul monitorizează căsuțele configurate și te ajută să răspunzi prompt:

### Vizualizare & Căutare Mesaje:
- *"Ce mailuri noi am pe UNITBV?"*
- *"Caută e-mailuri de la profesorul Popescu"*

### Redactare Răspuns & Aprobare (Human-in-the-Loop):
1. Când asistentul listează mesaje, include un buton direct `[ ✉️ Răspunde ]`.
2. Asistentul generează un draft politicos și profesional pe baza contextului universitar.
3. Sub draftul propus apar două butoane interactive:
   - `[ ✉️ Trimite ]` – Trimite e-mailul imediat prin serverul SMTP configurat.
   - `[ ❌ Anulează ]` – Anulează draftul fără a trimite nimic.

> **Securitate:** Niciun e-mail nu este trimis automat fără aprobarea ta explicită prin butonul inline sau prin mesaj text de confirmare!

---

## 📰 6. Știri Tehnologice & Inteligență Artificială

Asistentul preia și filtrează noutățile din fluxuri RSS credibile (ex. Hacker News, TechCrunch, ArXiv AI):
- Apasă pe `[ 📰 Știri IT & AI ]` sau întreabă: *"Ce noutăți sunt în AI astăzi?"*.
- Asistentul oferă cele mai relevante 3–5 știri, cu rezumate concise și link-uri către articolele sursă.

---

## ⏰ 7. Notificări Proactive & Briefing Matinal

Asistentul poate trimite automat alerte și rezumate fără a fi întrebat:

1. **Daily Morning Briefing:**
   În fiecare dimineață, primești o sinteză completă:
   - Evenimentele și cursurile zilei din Google Calendar.
   - Sarcinile academice urgente rămase de rezolvat.
   - Cele mai importante știri IT ale dimineții.

2. **Alerte Termene Limită Practică:**
   La apropierea datelor-cheie din calendarul UNITBV (28 august – finalizare practică, 2 septembrie – depunere documente, 5–10 septembrie – colocviu), asistentul emite automat o notificare push de reamintire cu buton rapid de descărcare documente.

---

## 🛡️ 8. Ce faci în caz de probleme?

- **Botul nu răspunde:** Verifică dacă tunelul ngrok este activ sau dacă adresa IP a webhook-ului s-a schimbat.
- **Cheie API fără cotă:** Asistentul dispune de un mecanism de **fallback automat pe modelul local Ollama (`qwen2.5:1.5b`)**, continuând să funcționeze chiar dacă furnizorul cloud întâmpină probleme de cotă.
