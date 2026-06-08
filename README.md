# App Bandi Gara 🚀

Applicazione per lo scraping e l'analisi dei bandi di gara basata su Python, `Crawl4AI` e visione artificiale (GPT-4o-mini).

## Architettura

```
app bandi gara/
├── service/crawl4ai/
│   ├── classificatoreLoginService.py   # Vision LLM — classifica stato pagina
│   ├── estrattoreSelettoriService.py   # DOM → LLM → selettori CSS con cache
│   ├── esecutoreLoginService.py        # Playwright — login + cookie manager
│   └── scraperService.py              # Loop principale sul DataFrame portali
├── model/
│   ├── po/portalePo.py                # Oggetto portale (da Excel)
│   ├── dto/                           # DTO risultati login e classificazione
│   └── enums/                         # Enum stati pagina, login, confidenza
├── promptDiSistema/
│   └── classificatoreLogin.py         # Prompt di sistema per il classificatore
├── user e password per Operations.xlsx # Sorgente dati portali
├── .env                               # Chiavi API (non committare)
├── Dockerfile
└── requirements.txt
```

## Prerequisiti

L'applicazione è interamente containerizzata. L'unico requisito sulla macchina è **Docker** (e **Docker Desktop** su Windows/macOS). 

---

## Come iniziare

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

### 4. Avvia l'applicazione

#### Windows (PowerShell)

```powershell
docker run --rm \
  --env-file .env \
  -v "${PWD}:/app" \
  app-bandi-gara
```

#### Linux / macOS

```bash
docker run --rm \
  --env-file .env \
  -v "$(pwd):/app" \
  app-bandi-gara
```

---

## Sviluppo locale (senza Docker)

Se preferisci girare il progetto direttamente in locale:

```bash
# 1. Crea e attiva il venv
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Linux/macOS

# 2. Installa le dipendenze
pip install -r requirements.txt

# 3. Installa il browser (obbligatorio, una volta sola)
playwright install chromium

# 4. Avvia
python app.py
```

---

## Come funziona il login automatico

Il sistema usa una strategia a più livelli per autenticarsi sui portali:

| Livello | Strategia | Quando si attiva |
|---------|-----------|-----------------|
| 0 | Cookie reuse | Sempre — se la sessione è ancora valida, salta il login |
| 1 | Vision LLM | Screenshot → GPT-4o-mini classifica la pagina |
| 2 | Estrazione DOM | LLM individua i selettori CSS del form senza hardcoding |
| 3 | Fallback premium | GPT-4o se la classificazione ha confidenza bassa |
| ⚠️ | Intervento manuale | OAuth, CAPTCHA, MFA — il portale viene flaggato nel log |

---

## File Excel portali

Il file `user e password per Operations.xlsx` deve contenere almeno queste colonne:

| Colonna | Descrizione |
|---------|-------------|
| `numero` | ID progressivo |
| `cliente` | Nome cliente |
| `gruppo` | Gruppo di appartenenza |
| `url` | URL della pagina di login |
| `username` | Username |
| `password` | Password |
| `note` | Note opzionali |

---

## Output e log

I cookie delle sessioni autenticate vengono salvati in `sessioni/` (creata automaticamente).
Il log a console mostra per ogni portale lo stato del login e un riepilogo finale:

```
✔ success          — login riuscito, cookie salvati
✔ skipped_cookie   — sessione riusata, nessuna chiamata LLM
✗ failed_creds     — credenziali errate
✗ failed_captcha   — CAPTCHA non superabile automaticamente
✗ failed_mfa       — MFA rilevato, richiede configurazione
✗ failed_manual    — OAuth/SSO, intervento umano necessario
```

---

## .gitignore consigliato

Verifica che il tuo `.gitignore` contenga almeno:

```
.env
venv/
sessioni/
__pycache__/
*.pyc
```
