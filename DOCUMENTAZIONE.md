Certamente! Puoi chiamarlo tranquillamente `DOCUMENTAZIONE.md` (o `ARCHITECTURE.md`) e tenerlo nella radice del progetto accanto al `README.md` principale. È una pratica comunissima nei progetti professionali: il `README.md` serve come guida rapida di installazione e avvio, mentre un file dedicato alla documentazione o all'architettura descrive come funziona il motore sotto il cofano.

Ecco l'intero documento formattato in un unico blocco Markdown, pronto da copiare e incollare nel tuo nuovo file:

```markdown
# 📜 Documentazione Tecnica di Architettura: Sistema Ingegnerizzato di Scraping Bandi

[cite_start]Il sistema è un framework di automazione e scraping asincrono in **Python 3.11+**, containerizzato tramite **Docker**, progettato per l'autenticazione automatica e l'estrazione strutturata di bandi di gara da portali di e-procurement[cite: 1, 2]. 

[cite_start]L'architettura unisce la stabilità del controllo del DOM di **Playwright** all'intelligenza semantica dei **Modelli di Linguaggio Generativi (LLM - GPT-4o / GPT-4o-mini)**[cite: 2, 5, 7].

---

## ── 📂 1. Mappatura Reale del File Tree
La struttura dei moduli, depurata dagli ambienti virtuali, si articola come segue:

```text
📦 app bandi gara
 ┣ 📂 config
 ┃ ┗ 📜 selettori_portali.json          # Cache dei selettori CSS (Discovery LLM)
 ┣ 📂 controller                        # Predisposizione per l'interfaccia Web/API
 ┣ 📂 dao                               # Predisposizione per la persistenza su DB MySQL
 ┣ 📂 model
 ┃ ┣ 📂 dto
 ┃ ┃ ┣ 📜 bandoDto.py                 # Modello Pydantic per i dati estratti del bando
 ┃ ┃ ┣ 📜 classificazioneLoginDto.py  # DTO per l'output del Vision LLM
 ┃ ┃ ┣ 📜 risultatoLoginDto.py        # DTO esito login (status, cookie path, ecc.)
 ┃ ┃ ┗ 📜 selettorePortaleDto.py      # Schema di configurazione dei selettori CSS
 ┃ ┗ 📂 enums
 ┃   ┣ 📜 confidenzaEnum.py           # Livelli di confidenza LLM (HIGH, MEDIUM, LOW)
 ┃   ┣ 📜 statoLoginEnum.py           # Stati del processo (SUCCESS, FAILED_ERROR, ecc.)
 ┃   ┗ 📜 statoPaginaEnum.py          # Classificazione pagina (LOGGED_IN, CAPTCHA, ecc.)
 ┣ 📂 promptDiSistema
 ┃ ┗ 📜 classificatoreLogin.py          # Prompt di sistema strutturati per la Vision API
 ┣ 📂 service
 ┃ ┣ 📂 crawl4ai                        # Core Engine di Scraping e Automazione
 ┃ ┃ ┣ 📜 classificatoreLoginService.py   # Analisi visiva della pagina pre/post-login
 ┃ ┃ ┣ 📜 esecutoreLoginService.py        # Driver Playwright con logica Stealth e Umana
 ┃ ┃ ┣ 📜 discoverySelettoriService.py  # LLM Discovery per la generazione dei selettori
 ┃ ┃ ┣ 📜 estrattoreBandiService.py       # Orchestratore estrazione (Deterministica vs LLM)
 ┃ ┃ ┣ 📜 estrattoreCssService.py         # Parsing nativo veloce del DOM tramite CSS
 ┃ ┃ ┣ 📜 estrattoreSelettoriService.py   # Fallback LLM ed estrazione ad alta confidenza
 ┃ ┃ ┗ 📜 scraperService.py               # Loop di orchestrazione principale e parallelizzazione
 ┃ ┗ 📂 estrazioneFile
 ┃   ┗ 📜 estrazioneDatiExcelService.py   # Generazione e formattazione dell'output Excel
 ┣ 📂 sessioni
 ┃ ┗ 📜 *.json                         # Cache dei cookie di autenticazione per portale
 ┗ 📂 static/templates/index.html       # Predisposizione per la Dashboard Frontend

```

---

## ── 🔄 2. Flusso Logico dei Macro-Moduli

### A. Sottosistema di Autenticazione Avanzata (`esecutoreLoginService.py`)

Progettato per superare le barriere di sicurezza (WAF come Cloudflare o Akamai) e le strutture enterprise a iFrame (es. SAP Ariba):

* **Profilazione Umanoide del Browser:** Lancio in modalità Headless offuscata tramite rimozione della proprietà `navigator.webdriver` ed emulazione di caratteristiche reali del browser.
* 
**Rilevamento Visivo dello Stato (`classificatoreLoginService.py`):** La pagina iniziale viene scansionata tramite screenshot inviati a `gpt-4o-mini` (Vision) per validare lo stato (es. se c'è un Captcha, una form di login o se si è già loggati).


* **Digitazione Sequenziale Variabile:** Inserimento delle credenziali simulando le dita sulla tastiera (`press_sequentially`) con ritardi randomici (40-120ms a carattere) per ingannare i controlli comportamentali dei firewall.
* **Isolamento iFrame:** Iniezione dinamica dei selettori all'interno dei sotto-frame qualora il form non risiedesse nel documento principale.

### B. Strategia di Estrazione Ibrida dei Bandi (`estrattoreBandiService.py`)

Per scalare su oltre 114 portali riducendo i costi di API a regime, il sistema applica l'**Approccio C (Ibrido / Deterministico-Semantico)**:

1. 
**Fase Deterministica Veloce (`estrattoreCssService.py`):** Se il portale ha una struttura nota in cache, estrae i dati in millisecondi a costo computazionale zero.


2. 
**Fase di Discovery Autonoma (`discoverySelettoriService.py`):** Se la struttura è sconosciuta o mutata, l'LLM analizza l'HTML, individua i pattern strutturali e propone un modello CSS. Se i selettori estraggono un numero di bandi $\ge 3$, vengono promossi a "Configurazione Affidabile" e salvati nel file JSON.


3. 
**Fase Fallback Semantico (`estrattoreSelettoriService.py`):** Se i selettori in cache falliscono o estraggono meno di 3 bandi, il sistema esegue un parsing semantico full-text tramite LLM restituendo i risultati grezzi.



---

## ── 📊 3. Persistenza dei Dati e Output

* 
**Output Attuale:** Esportazione aggregata finale dei dati dei bandi, accuratamente tipizzati tramite modelli Pydantic, all'interno del foglio elettronico `bandi_estratti_totale.xlsx`.


* **Sviluppo in Corso:** Il layer di acesso ai dati è già predisposto (cartella `dao`) per spostare lo storage dei bandi e lo storico delle sessioni su un database relazionale **MySQL**.

---

## ── 🚀 4. Tabella di Marcia per i Prossimi Sviluppi

1. 
**Gestione Intelligente dei Cookie:** Implementare un controllo preliminare sulla cartella `sessioni/`. Se il file JSON del portale esiste ed è recente, lo scraper deve saltare la routine di login e iniettare direttamente i cookie in Playwright, riducendo il carico sui server e l'uso delle API.


2. **Normalizzazione e Traduzione Multilingua:** Aggiornare i prompt dei moduli di estrazione per abilitare la traduzione automatica in tempo reale in italiano dei campi `titolo` e `descrizione` quando si scansionano i portali europei/internazionali (es. SAP Ariba, Oracle Cloud).
3. **Attivazione Layer Database (DAO):** Collegare i modelli Pydantic al database MySQL tramite un ORM (come SQLAlchemy) o query dirette, per centralizzare i dati estratti superando i limiti fisici del file Excel.

```

