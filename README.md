# App Bandi Gara 🚀

Applicazione per lo scraping e l'analisi dei bandi di gara basata su Python, `Crawl4AI` e visione artificiale (GPT-4o-mini).

## 🏗️ Architettura (Model-View-Presenter)

L'applicazione segue l'architettura **MVP** per garantire il disaccoppiamento tra il framework web (Flask), la logica di business e lo storage dei dati:

```
app bandi gara/
├── dao/                                # Model Layer: Data Access Objects
│   ├── portaleDao.py                   # Carica i dati dei portali da Excel
│   └── bandoDao.py                     # Salva i bandi ed estrae le metriche da Excel
├── view/                               # View Layer: Formattazione dei risultati
│   └── scraperView.py                  # ScraperViewInterface e FlaskScraperView (JSON)
├── presenter/                          # Presenter Layer: Coordinamento e threading
│   └── scraperPresenter.py             # Riceve richieste, avvia i thread e aggiorna la View
├── controller/                         # Routing Layer: Ingressi HTTP Flask
│   └── indexController.py              # Inoltra le rotte /api al Presenter
├── service/crawl4ai/                   # Model Layer: Motori di Scraping e IA
│   ├── browserFactory.py               # Configura ed avvia browser Playwright stealth
│   ├── formFillerService.py            # Riempie i form e simula la digitazione umana
│   ├── navigatoreLlmService.py         # Naviga alla sezione bandi guidato da LLM
│   ├── classificatoreLoginService.py   # Vision LLM — classifica stato pagina
│   ├── estrattoreSelettoriService.py   # DOM → LLM → selettori CSS con cache
│   ├── esecutoreLoginService.py        # Gestisce i tentativi di login sui portali
│   └── scraperService.py               # Orchestratore principale del loop di scraping
├── model/                              # DTO, PO ed Enums
│   ├── po/portalePo.py                 # Dataclass per la configurazione del portale
│   ├── dto/                            # Pydantic Schemas per input/output LLM
│   └── enums/                          # Stati di login, pagina e confidenza
├── promptDiSistema/
│   └── classificatoreLogin.py          # Prompt di sistema per la Vision API
├── user e password per Operations.xlsx # Sorgente dati portali
├── .env                                # Chiavi API (non committare)
├── Dockerfile
└── requirements.txt

```

---

## 📋 Prerequisiti

L'applicazione è interamente containerizzata. L'unico requisito sulla macchina è **Docker** (e **Docker Desktop** su Windows/macOS).

---

## 🚀 Come iniziare

### 1. Clona la repository

```bash
git clone <URL_DELLA_TUA_REPO_QUI>
cd "app bandi gara"

```

### 2. Configura le variabili d'ambiente

Crea un file `.env` nella root del progetto (non viene mai committato su git):

```env
OPENAI_API_KEY=sk-...

```

### 3. Costruisci l'immagine Docker

Da eseguire solo la prima volta o dopo modifiche al `requirements.txt`:

```bash
docker build -t app-bandi-gara .

```

---

## 🐳 Avvio con Docker

A seconda del terminale che stai utilizzando e delle tue necessità, scegli il comando corretto.

### Caso A: Solo Scraper / Script (Senza interfaccia Web)

Usa questi comandi se vuoi lanciare lo scraper direttamente nel terminale senza esporre porte di rete.

* **In riga singola (Universale / Bash):**
```bash
docker run --rm --env-file .env -v "$(pwd):/app" app-bandi-gara

```


* **Specifico per Windows (PowerShell):**
```powershell
docker run --rm `
  --env-file .env `
  -v "$PWD:/app" `
  app-bandi-gara

```



### Caso B: Con API / Interfaccia Web (Porta 5000)

Usa questi comandi se l'applicazione fa partire il server Flask e hai bisogno di raggiungere gli endpoint (`/api/avvia`, `/api/scarica-excel`, ecc.) dal tuo browser su `http://localhost:5000`.

* **In riga singola (Universale / Bash):**
```bash
docker run --rm -p 5000:5000 --env-file .env -v "$(pwd):/app" app-bandi-gara

```


* **Specifico per Windows (PowerShell):**
```powershell
docker run --rm `
  -p 5000:5000 `
  --env-file .env `
  -v "$PWD:/app" `
  app-bandi-gara

```



---

## 💻 Sviluppo locale (senza Docker)

Se preferisci far girare il progetto direttamente in locale sul tuo sistema:

```bash
# 1. Crea e attiva il venv
python -m venv venv
venv\Scripts\activate      # Windows
source venv/bin/activate     # Linux/macOS

# 2. Installa le dipendenze
pip install -r requirements.txt

# 3. Installa il browser (obbligatorio, una volta sola)
playwright install chromium

# 4. Avvia
python app.py

```

---

## 🧠 Come funziona il login automatico

Il sistema usa una strategia a più livelli per autenticarsi sui portali:

| Livello | Strategia | Quando si attiva |
| --- | --- | --- |
| **0** | Cookie reuse | Sempre — se la sessione è ancora valida, salta il login |
| **1** | Vision LLM | Screenshot $\rightarrow$ GPT-4o-mini classifica la pagina |
| **2** | Estrazione DOM | LLM individua i selettori CSS del form senza hardcoding |
| **3** | Fallback premium | GPT-4o se la classificazione ha confidenza bassa |
| **⚠️** | Intervento manuale | OAuth, CAPTCHA, MFA — il portale viene flaggato nel log |

---

## 📊 File Excel portali

Il file `user e password per Operations.xlsx` deve essere inserito nella root del progetto e deve contenere almeno queste colonne:

| Colonna | Descrizione |
| --- | --- |
| `numero` | ID progressivo |
| `cliente` | Nome cliente |
| `gruppo` | Gruppo di appartenenza |
| `url` | URL della pagina di login |
| `username` | Username |
| `password` | Password |
| `note` | Note opzionali |

---

## 📝 Output e log

* I cookie delle sessioni autenticate vengono salvati in `sessioni/` (cartella creata automaticamente).
* Il log a console mostra per ogni portale lo stato del login e un riepilogo finale:

```text
✔ success         — login riuscito, cookie salvati
✔ skipped_cookie   — sessione riusata, nessuna chiamata LLM
✗ failed_creds     — credenziali errate
✗ failed_captcha   — CAPTCHA non superabile automaticamente
✗ failed_mfa       — MFA rilevato, richiede configurazione
✗ failed_manual    — OAuth/SSO, intervento umano necessario

```

---

## 🚫 .gitignore consigliato

Verifica che il tuo file `.gitignore` contenga almeno le seguenti voci per evitare di tracciare file sensibili o temporanei:

```text
.env
venv/
sessioni/
__pycache__/
*.pyc
*.xlsx

```