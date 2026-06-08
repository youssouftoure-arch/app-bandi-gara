---

```markdown
# 📜 Documentazione Tecnica di Architettura: Sistema Ingegnerizzato di Scraping Bandi

Il sistema è un framework di automazione e scraping asincrono in **Python 3.11+**, containerizzato tramite **Docker**, progettato per l'autenticazione automatica, l'estrazione strutturata e la visualizzazione in tempo reale di bandi di gara da portali di e-procurement. 

L'architettura unisce la stabilità del controllo del DOM di **Playwright** all'intelligenza semantica dei **Modelli di Linguaggio Generativi (LLM - GPT-4o / GPT-4o-mini)**, esponendo le metriche e il controllo operativo tramite un'interfaccia web asincrona basata su **Flask**.

---

## ── 📂 1. Mappatura Reale del File Tree
La struttura dei moduli, ingegnerizzata secondo il pattern a micro-servizi e la separazione delle responsabilità tramite Blueprint, si articola come segue:

```text
📦 app bandi gara
 ┣ 📂 config
 ┃ ┗ 📜 selettori_portali.json          # Cache dei selettori CSS (Discovery LLM)
 ┣ 📂 controllers
 ┃ ┗ 📜 scraper_controller.py          # Blueprint Flask: API REST (/api/avvia, /api/stato, /api/dati)
 ┣ 📂 dao                               # Predisposizione per la persistenza su DB MySQL
 ┣ 📂 model
 ┃ ┣ 📂 dto
 ┃ ┃ ┣ 📜 bandoDto.py                 # Modello Pydantic con validazione date ≥ 2026 e normalizzazione URL
 ┃ ┃ ┣ 📜 classificazioneLoginDto.py  # DTO per l'output del Vision LLM
 ┃ ┃ ┣ 📜 risultatoLoginDto.py        # DTO esito login (status, cookie path, ecc.)
 ┃ ┃ ┗ 📜 selettorePortaleDto.py      # Schema di configurazione dei selettori CSS
 ┃ ┗ 📂 enums
 ┃    ┣ 📜 confidenzaEnum.py           # Livelli di confidenza LLM (HIGH, MEDIUM, LOW)
 ┃    ┣ 📜 statoLoginEnum.py           # Stati del processo (SUCCESS, FAILED_ERROR, ecc.)
 ┃    ┗ 📜 statoPaginaEnum.py          # Classificazione pagina (LOGGED_IN, CAPTCHA, ecc.)
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
 ┃    ┗ 📜 estrazioneDatiExcelService.py   # Generazione, pulizia dati e formattazione output Excel
 ┣ 📂 static
 ┃ ┗ 📂 css
 ┃    ┗ 📜 style.css                   # Stile CSS esterno per la Dashboard (Enterprise-ready)
 ┣ 📂 templates
 ┃ ┗ 📜 index.html                      # Interfaccia UI asincrona (Fetch API) per il controllo dei cicli
 ┣ 📂 sessioni
 ┃ ┗ 📜 *.json                          # Cache dei cookie di autenticazione per portale
 ┣ 📜 .env                              # Chiavi API e configurazioni sensibili (Scopo locale)
 ┣ 📜 Dockerfile                        # Definizione dell'ambiente isolato Linux/Playwright
 ┣ 📜 README.md                         # Manuale operativo di installazione e avvio rapido
 ┣ 📜 requirements.txt                  # Dipendenze rigidamente tracciate (Flask, Crawl4AI, Openpyxl)
 ┗ 📜 user e password per Operations.xlsx # Sorgente dati d'ingresso (Anagrafica Portali)

```

---

## ── 🔄 2. Flusso Logico dei Macro-Moduli

### A. Sottosistema di Autenticazione Avanzata (`esecutoreLoginService.py`)

Progettato per superare le barriere di sicurezza (WAF come Cloudflare o Akamai) e le strutture enterprise a iFrame (es. SAP Ariba):

* **Profilazione Umanoide del Browser:** Lancio in modalità Headless offuscata tramite rimozione della proprietà `navigator.webdriver` ed emulazione di caratteristiche reali del browser.
* **Rilevamento Visivo dello Stato (`classificatoreLoginService.py`):** La pagina iniziale viene scansionata tramite screenshot inviati a `gpt-4o-mini` (Vision) per validare lo stato (es. se c'è un Captcha, una form di login o se si è già loggati).
* **Digitazione Sequenziale Variabile:** Inserimento delle credenziali simulando le dita sulla tastiera (`press_sequentially`) con ritardi randomici (40-120ms a carattere) per ingannare i controlli comportamentali dei firewall.
* **Isolamento iFrame:** Iniezione dinamica dei selettori all'interno dei sotto-frame qualora il form non risiedesse nel documento principale.

### B. Strategia di Estrazione Ibrida e Pulizia Dati Semantica

Per scalare su oltre 114 portali riducendo i costi di API a regime, il sistema applica l'**Approccio Ibrido / Deterministico-Semantico**:

1. **Fase Deterministica Veloce (`estrattoreCssService.py`):** Se il portale ha una struttura nota in cache, estrae i dati in millisecondi a costo computazionale zero.
2. **Fase di Discovery Autonoma (`discoverySelettoriService.py`):** Se la struttura è sconosciuta o mutata, l'LLM analizza l'HTML, individua i pattern strutturali e propone un modello CSS. Se i selettori estraggono un numero di bandi $\ge 3$, vengono promossi a "Configurazione Affidabile" e salvati nel file JSON.
3. **Fase Fallback Semantico (`estrattoreSelettoriService.py`):** Se i selettori in cache falliscono, il sistema esegue un parsing semantico full-text tramite LLM.

#### 🛡️ Regole Rigide di Business Logic e Validazione (`bandoDto.py`)

Il modulo integra un sistema di pulizia e normalizzazione automatica dei dati grezzi estratti dall'LLM prima di inviarli allo storage:

* **Filtro Temporale Rigido (`@field_validator`):** Il sistema intercetta le scadenze storiche. Qualsiasi bando avente una data antecedente all'anno in corso (**2026**) viene intercettato da Pydantic e **scartato automaticamente**, evitando il popolamento del database con record obsoleti o archiviati.
* **Iniezione Dinamica del Committente:** Il DTO prevede l'estrazione semantica della Stazione Appaltante. Qualora l'LLM non riesca a mappare il committente dal testo della pagina, l'orchestratore attiva un algoritmo di fallback che isola il dominio del portale web (es. ricavando `STRADEANAS` da `acquisti.stradeanas.it`) normalizzandolo in lettere maiuscole.
* **Anti-Anomalia URL (`normalizza_url`):** Risolve i bug derivanti dall'estrazione di script asincroni o variabili Javascript non definite (es. stringhe corrotte contenenti frammenti come `successundefined`). In caso di link malformati, il sistema esegue un fallback iniettando l'URL radice del portale per permettere la verifica manuale dell'operatore dalla Dashboard.

---

## ── 🌐 3. Struttura del Web Server & Controllo Asincrono

Il sistema abbandona l'esecuzione monolitica da terminale a favore di un'architettura disaccoppiata basata su **Flask**:

```
[ Browser Client ] ──( Fetch API Asincrone )──> [ scraper_controller (Blueprint) ]
                                                            │ (Thread Dedicato)
                                                            ▼
                                                [ core / scraperService ]
                                                            │
                                                            ▼
                                              [ bandi_estratti_totale.xlsx ]

```

* **Controllo Non-Bloccante:** Le richieste di avvio del ciclo inviate all'endpoint `/api/avvia` istanziano un thread nativo (`threading.Thread`). Questo permette al motore di scraping di operare in background senza congelare il server HTTP.
* **Polling dello Stato:** L'interfaccia frontend esegue un polling asincrono JavaScript verso l'endpoint `/api/stato` per variare dinamicamente lo stato visivo della dashboard (da *Pronto* a *Scraping in corso...*).
* **Consumo Dati JSON:** L'endpoint `/api/dati` si occupa di leggere il file `bandi_estratti_totale.xlsx` tramite **Pandas**, convertendo i record in vettori JSON strutturati. I valori nulli o i campi `None` indotti dall'LLM vengono intercettati e normalizzati con caratteri di riempimento standard (`-`) per garantire l'integrità visiva delle celle HTML.

---

## ── 🐳 4. Deployment, Networking e Containerizzazione

Il sistema è interamente containerizzato per azzerare le problematiche legate alle dipendenze dei browser binari di Playwright.

* **Isolamento di Rete (Bridging Docker):** All'interno del container Docker, il server Flask è configurato per ascoltare sull'indirizzo host universale `0.0.0.0`. Questo permette di instradare il traffico di rete oltre i confini del localhost isolato del container.
* **Mappatura delle Porte:** Il comando di esecuzione effettua un port-forwarding esplicito `-p 5000:5000`. Il traffico generato sul browser della macchina ospite (host) viene così rediretto in modo deterministico sul Web Server Flask interno al container Linux.
* **Persistenza Real-Time:** Tramite i volumi Docker (`-v`), il file di output `bandi_estratti_totale.xlsx` e la cartella delle sessioni persistono direttamente sul file system fisico dello sviluppatore, rendendo le estrazioni immuni alla distruzione o al riavvio del container.

---

## ── 🚀 5. Tabella di Marcia per i Prossimi Sviluppi

1. **Integrazione DAO/Database Regionale:** Sostituzione dei file Excel di output intermedi con scritture transazionali dirette su tabelle MySQL mediante la cartella `dao` già predisposta.
2. **Traduzione Semantica Real-Time:** Abilitazione nei prompt dell'LLM della traduzione automatica in lingua italiana per i portali di e-procurement esteri europei (es. SAP Ariba / Oracle Cloud).
3. **Ottimizzazione Avanzata Cookie:** Estensione della routine di skip automatico del login analizzando la scadenza effettiva dei token all'interno dei file JSON nella cartella `sessioni/`.

```

```
