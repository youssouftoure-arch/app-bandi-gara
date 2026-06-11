# Documentazione Tecnica - Sistema Scraping Bandi

Questa documentazione descrive l'architettura reale del progetto dopo il refactor dei servizi di scraping. L'obiettivo dell'applicazione e' autenticarsi su portali di e-procurement, individuare le sezioni bandi, estrarre dati strutturati, salvarli in Excel e mostrarli tramite una dashboard Flask.

Il sistema combina:

- Flask per API HTTP, dashboard e download dei risultati.
- Playwright per browser automation, login e navigazione.
- OpenAI GPT-4o / GPT-4o-mini per classificazione visiva, discovery dei selettori e parsing semantico.
- Pandas/Openpyxl per lettura e scrittura Excel.
- Pydantic/dataclass per DTO, validazione e contratti tra moduli.

---

## 1. Entry Point e Layer Web

### `app.py`

Entry point Flask dell'applicazione.

Responsabilita':

- crea l'istanza `Flask`;
- registra il blueprint API definito in `controller/indexController.py`;
- espone la rotta `/`, che renderizza `templates/index.html`;
- avvia il server locale su `0.0.0.0:5000` in debug mode quando eseguito direttamente.

### `controller/indexController.py`

Controller HTTP basato su Flask Blueprint, con prefisso `/api`.

Endpoint esposti:

- `POST /api/avvia`: avvia il ciclo di scraping in background tramite presenter;
- `GET /api/stato`: restituisce stato corrente e metriche finali;
- `GET /api/dati`: restituisce i bandi letti dall'Excel di output;
- `GET /api/scarica-excel`: invia `bandi_estratti_totale.xlsx` come download;
- `GET /api/dashboard`: renderizza `templates/dashboard.html`.

Dipendenze principali:

- `FlaskScraperView` per risposte JSON coerenti;
- `ScraperPresenter` per coordinare il caso d'uso;
- `AnalyticsService` per KPI e dati grafici.

### `presenter/scraperPresenter.py`

Presenter del pattern MVP.

Responsabilita':

- impedisce avvii duplicati se uno scraping e' gia' in corso;
- lancia lo scraping in un thread daemon;
- crea un event loop asincrono isolato per `scraper().main()`;
- calcola metriche finali lato presenter;
- espone stato e dati alla View;
- svuota l'output se il ciclo finisce con zero bandi.

Nota: il service `scraperService.py` possiede anche uno stato interno piu' dettagliato. Il presenter mantiene uno stato semplificato per gli endpoint web.

### `view/scraperView.py`

Layer View del pattern MVP.

Contiene:

- `ScraperViewInterface`: contratto astratto delle risposte;
- `FlaskScraperView`: implementazione concreta con `jsonify`.

Produce risposte JSON per stato, dati, avvio riuscito, avvio bloccato ed errori.

---

## 2. Model, DTO ed Enum

### `model/po/portalePo.py`

Rappresenta un portale da processare.

Campi principali:

- credenziali operative: `username`, `password`;
- URL: `url`, `url_bandi`;
- stato login: `login_type`, `captcha_type`, `mfa_type`;
- cache: `selectors_cached`, `cookies_path`, `last_login_ok`;
- flags: `requires_manual`, `is_active`.

Proprieta' importanti:

- `url_scraping`: usa `url_bandi` se presente, altrimenti `url`;
- `has_valid_session`: controlla TTL dei cookie;
- `needs_manual_intervention`: blocca portali con OAuth/SAML, CAPTCHA o MFA manuale.

Metodo di mapping:

- `from_dataframe_row(row)`: converte una riga Excel normalizzata in `Portale`.

### `model/dto/bandoDto.py`

DTO Pydantic del bando.

Campi:

- `titolo`;
- `committente`;
- `descrizione`;
- `scadenza`;
- `importo`;
- `categoria`;
- `url_dettaglio`.

Metodo importante:

- `normalizza_url(url_estratto, url_base)`: risolve link relativi e sostituisce URL corrotti contenenti `undefined` o `success` con l'URL base.

### `model/dto/risultatoLoginDto.py`

DTO dataclass dell'esito login.

Contiene:

- identificativo portale e URL;
- `LoginStatus`;
- path cookie e validita' sessione;
- stato pagina rilevato dal vision model;
- dati MFA;
- messaggio errore;
- retry count;
- selettori usati.

Proprieta':

- `is_success`: true per `SUCCESS` e `SKIPPED_COOKIE`.

### `model/dto/classificazioneLoginDto.py`

DTO della classificazione visiva della pagina.

Campi:

- `state`: valore `PageState`;
- `confidence`: valore `Confidence`;
- `notes`: nota breve prodotta dal modello;
- `used_model`: modello usato;
- `raw_json`: payload grezzo LLM.

### `model/dto/selettorePortaleDto.py`

Schemi Pydantic per selettori CSS dei bandi.

`ConfigSelettori` descrive:

- contenitore della riga/card bando;
- titolo;
- descrizione;
- scadenza;
- importo;
- categoria;
- URL dettaglio.

`PortaleConfigSchema` descrive la configurazione persistita con data discovery, affidabilita' e conteggio ultimo test.

### Enum

- `model/enums/statoLoginEnum.py`: esiti del login automatico.
- `model/enums/statoPaginaEnum.py`: stati pagina rilevati dal vision classifier.
- `model/enums/confidenzaEnum.py`: livelli di confidenza LLM.

---

## 3. DAO e Persistenza Dati

### `dao/portaleDao.py`

Legge il file operativo `user e password per Operations.xlsx`.

Flusso:

1. apre l'Excel con header alla riga 5 (`header=4`);
2. normalizza i nomi colonna;
3. crea oggetti `Portale`;
4. scarta righe vuote o non valide;
5. restituisce solo portali con `is_active=True`.

### `dao/bandoDao.py`

Gestisce l'Excel di output `bandi_estratti_totale.xlsx`.

Responsabilita':

- `carica_dati_bandi()`: legge l'Excel e restituisce records JSON-ready;
- `leggi_metriche()`: calcola KPI da Excel con fallback statici;
- `salva_bandi(risultati)`: converte risultati scraping in righe Excel;
- `estrai_committente_da_url(url)`: ricava un fallback committente dal dominio.

Regole applicate in salvataggio:

- se un portale non produce bandi, scrive una riga segnaposto;
- se la scadenza contiene `2025`, il bando viene saltato;
- se l'URL dettaglio e' assente o contiene `undefined`, viene sostituito con l'URL portale;
- il committente viene salvato in maiuscolo.

### `service/estrazioneFile/estrazioneDatiExcelService.py`

Servizio legacy per leggere portali da Excel e normalizzare URL mancanti di protocollo.

Nota: oggi il flusso principale usa `PortaleDao`; questo file resta utile come utility/compatibilita'.

---

## 4. Motore Scraping: Orchestrazione

### `service/crawl4ai/scraperConfig.py`

Centralizza configurazione dello scraper:

- `LOG_FILE_PATH`;
- `CACHE_FILE_PATH`;
- `EXCEL_PATH`;
- `CONCORRENZA`;
- `OPENAI_KEY`;
- `configura_logging()`.

Esegue `load_dotenv()` e legge `OPENAI_API_KEY` dall'ambiente.

### `service/crawl4ai/scraperService.py`

Orchestratore principale.

Responsabilita':

- istanzia client OpenAI e servizi core;
- carica portali tramite `PortaleDao`;
- processa portali in parallelo limitato da `CONCORRENZA`;
- coordina login ed estrazione bandi;
- aggiorna stato thread-safe;
- salva risultati progressivi e finali tramite `BandoDao`;
- produce riepilogo finale tramite `reportScraperService`.

Metodi principali:

- `main()`: ciclo asincrono completo sui portali;
- `_processa_portale(portale)`: login + scraping bandi per singolo portale;
- `_scrapa_e_estrai_bandi(portale, cookies_path)`: wrapper compatibile che delega alla pipeline portale;
- `get_stato()`: copia thread-safe dello stato interno.

Compatibilita':

- la classe mantiene il nome storico `scraper`;
- i wrapper privati `_carica_file_cache`, `_salva_file_cache`, `_stampa_bandi`, `_stampa_riepilogo` restano disponibili, ma delegano a moduli specializzati.

### `service/crawl4ai/reportScraperService.py`

Funzioni pure per reportistica:

- `stato_login_success()`;
- `formatta_durata()`;
- `stampa_bandi()`;
- `stampa_riepilogo()`.

Riduce duplicazione tra orchestratore e presenter.

---

## 5. Login Automatico

### `service/crawl4ai/esecutoreLoginService.py`

Servizio che esegue il login su un portale.

Flusso:

1. se esiste una sessione cookie valida, ritorna `SKIPPED_COOKIE`;
2. se il portale richiede intervento manuale, ritorna `FAILED_MANUAL`;
3. apre browser Playwright;
4. tenta login con retry;
5. classifica la pagina prima del submit;
6. estrae selettori login se serve;
7. compila form;
8. riclassifica dopo il submit;
9. salva sessione se login riuscito.

Costanti:

- `TIMEOUT_NAV = 30000`;
- `TIMEOUT_PORT = 90`;
- `MAX_RETRY = 2`.

### `service/crawl4ai/classificatoreLoginService.py`

Classifica screenshot tramite modello vision.

Usa:

- `gpt-4o-mini` come modello primario;
- `gpt-4o` come fallback se la confidence e' `LOW` o se richiesto con `force_premium`.

Metodi:

- `classify(path)`;
- `classify_bytes(bytes)`;
- `_call_vision()`.

### `service/crawl4ai/classificazioneLoginParser.py`

Parser difensivo della risposta JSON del classificatore.

Responsabilita':

- rimuove eventuali fence markdown;
- valida JSON;
- normalizza `state` in `PageState`;
- normalizza `confidence` in `Confidence`;
- ritorna `UNKNOWN/LOW` se la risposta non e' valida.

### `promptDiSistema/classificatoreLogin.py`

Prompt di sistema del classificatore vision.

Definisce schema obbligatorio:

- `state`;
- `confidence`;
- `notes`.

Stati ammessi:

- `standard_form`;
- `oauth_sso`;
- `captcha_present`;
- `mfa_otp`;
- `logged_in`;
- `error_page`;
- `unknown`.

### `service/crawl4ai/estrattoreSelettoriService.py`

Estrae i selettori CSS per form di login.

Flusso:

1. se i selettori sono in cache sul `Portale`, li riusa;
2. chiede a `gpt-4o-mini`;
3. se confidence e' sotto soglia, passa a `gpt-4o`;
4. salva i selettori sul portale se superano `CONFIDENCE_MINIMA`.

Output atteso:

- `username`;
- `password`;
- `submit`;
- `confidence`.

### `service/crawl4ai/formFillerService.py`

Compila e invia il form di login.

Caratteristiche:

- cerca il form nella pagina principale;
- se non trova il campo username, cerca negli iframe;
- usa selettori primari e fallback generici;
- simula digitazione sequenziale con ritardi casuali;
- prova click standard, click forzato e invio con Enter.

### `service/crawl4ai/sessioneLoginService.py`

Persiste la sessione riuscita.

Responsabilita':

- legge cookie dal context Playwright;
- salva JSON in `sessioni/{numero}_{cliente}.json`;
- aggiorna `cookies_path` e `last_login_ok` sul portale;
- ritorna `LoginResult(status=SUCCESS)`.

### `service/crawl4ai/browserFactory.py`

Factory centralizzata per browser Playwright.

Configura:

- Chromium;
- headless mode;
- viewport;
- user agent;
- locale `it-IT`;
- timezone `Europe/Rome`;
- accept downloads;
- script anti-`navigator.webdriver`.

---

## 6. Navigazione e Profilazione Bandi

### `service/crawl4ai/navigatoreLlmService.py`

Decide quale link della pagina conduce alla sezione bandi.

Input:

- URL corrente;
- lista link estratti dal DOM.

Output:

- URL selezionato dall'LLM;
- fallback a `url_corrente` in caso di errore o risposta non valida.

### `service/crawl4ai/profilazioneCacheService.py`

Legge e scrive la cache JSON di profilazione.

File usato:

- `config/profiler_cache.json`.

Contenuto tipico:

- URL sezione bandi;
- selettori CSS locali;
- timestamp `last_updated`.

### `service/crawl4ai/profilatoreBandiPortaleService.py`

Gestisce la profilazione del portale.

Flusso:

1. legge la cache;
2. considera valida una profilazione se aggiornata da meno di 7 giorni;
3. se cache valida, ritorna URL e selettori;
4. se cache assente o scaduta, chiede al navigatore LLM l'URL della sezione bandi;
5. usa `DiscoverySelettoriService` per ricavare selettori;
6. se la discovery fallisce, usa `FALLBACK_SELETTORI`;
7. salva la nuova profilazione.

### `service/crawl4ai/discoverySelettoriService.py`

Analizza HTML bandi e propone selettori CSS.

Responsabilita':

- pulisce HTML da script, style, header, footer, nav e allegati;
- chiede all'LLM un set di selettori per lista bandi;
- testa i selettori tramite `EstrattoreCssService`;
- salva configurazioni in `config/selettori_portali.json`;
- fornisce fallback full-text LLM se i selettori non bastano.

### `model/dto/selettorePortaleDto.py`

Contratto dei selettori bandi usati da discovery e cache.

---

## 7. Estrazione Bandi

### `service/crawl4ai/scrapingBandiPortaleService.py`

Pipeline Playwright per un singolo portale gia' autenticato.

Flusso:

1. carica cookie se disponibili;
2. apre browser/context;
3. naviga alla pagina base di scraping;
4. ottiene profilo portale da cache o discovery;
5. naviga alla sezione bandi;
6. attende il selettore contenitore;
7. legge HTML;
8. se cache valida, prova fast track CSS;
9. se CSS fallisce o cache non valida, usa slow track LLM;
10. apre eventuali pagine dettaglio e arricchisce ogni bando.

### `service/crawl4ai/estrattoreCssService.py`

Estrazione deterministica via BeautifulSoup e selettori CSS.

Input:

- HTML;
- dizionario selettori;
- URL base.

Output:

- lista di `Bando`.

Regola di sicurezza:

- se `contenitore_bando` e' vuoto, ritorna lista vuota evitando errori CSS selector.

### `service/crawl4ai/estrattoreBandiService.py`

Estrae l'elenco iniziale dei bandi tramite LLM.

Responsabilita':

- pulisce HTML riducendo rumore;
- tronca testo troppo lungo;
- chiede all'LLM titolo e URL dettaglio;
- normalizza URL dettaglio;
- mantiene il metodo batch legacy `arricchisci_bandi`.

### `service/crawl4ai/estrattoreDettagliBandoService.py`

Arricchisce un singolo bando leggendo la pagina dettaglio.

Campi estratti:

- importo;
- scadenza;
- descrizione;
- categoria.

Regola importante:

- non sovrascrive un campo gia' presente se l'LLM ritorna `null`.

### `service/crawl4ai/schemaEstrazioneBandi.py`

Schemi Pydantic usati come `response_format` nelle chiamate LLM.

Contiene:

- `ElencoBandiOutput`;
- `DettagliBandoOutput`.

---

## 8. Dashboard e Frontend

### `templates/index.html`

Dashboard operativa principale.

Funzioni:

- avvio scraping;
- polling stato;
- visualizzazione metriche finali;
- tabella dei bandi;
- download Excel;
- link a dashboard grafici.

### `templates/dashboard.html`

Dashboard analytics.

Mostra:

- KPI totali;
- distribuzione bandi per portale;
- ultimi bandi estratti;
- messaggi di errore se Excel non esiste.

### `service/grafici/plotService.py`

Prepara i dati per `dashboard.html`.

Calcola:

- totale bandi reali;
- portali scansionati;
- labels/conteggi per grafico;
- ultimi 10 bandi.

### `static/css/style.css`

Stile della dashboard operativa:

- layout;
- container;
- pulsanti;
- stati;
- tabelle;
- card e pannelli.

---

## 9. File di Configurazione, Cache e Output

### `.env`

Contiene variabili sensibili, in particolare:

- `OPENAI_API_KEY`.

Non deve essere versionato se contiene credenziali reali.

### `config/selettori_portali.json`

Cache/configurazione dei selettori bandi scoperti da `DiscoverySelettoriService`.

Non contiene commenti perche' JSON standard non li supporta.

### `config/profiler_cache.json`

Cache della profilazione rapida usata da `ProfilatoreBandiPortaleService`.

Memorizza:

- URL sezione bandi;
- selettori;
- data ultimo aggiornamento.

Non contiene commenti perche' JSON standard non li supporta.

### `sessioni/*.json`

Cookie Playwright salvati dopo login riuscito.

Uso:

- evitare login ripetuti;
- accelerare scraping successivi;
- ridurre rischio CAPTCHA/MFA.

### `bandi_estratti_totale.xlsx`

Output Excel principale.

Prodotto da:

- `BandoDao.salva_bandi()`.

Letto da:

- `BandoDao.carica_dati_bandi()`;
- `AnalyticsService.ottieni_dati_dashboard()`;
- endpoint `/api/scarica-excel`.

### `scraper_activity.log`

Log runtime dello scraper.

Contiene:

- avvio browser;
- login;
- cache hit/miss;
- navigazioni;
- conteggi bandi;
- errori tecnici.

### `requirements.txt`

Manifest delle dipendenze Python.

Nota tecnica: nel workspace attuale il file e' codificato in UTF-16LE. Non e' stato modificato durante questa passata per evitare conversioni di encoding non richieste.

### `Dockerfile`

Definisce l'immagine applicativa:

- base `python:3.11-slim`;
- installa dipendenze Linux per Chromium/Playwright;
- installa `requirements.txt`;
- installa browser Chromium;
- copia il progetto;
- avvia `python app.py`.

### `bandi.sql`

Schema SQL iniziale per tabella portali/credenziali.

Oggi il flusso principale usa Excel, ma il file resta utile come base per futura persistenza MySQL.

---

## 10. Flussi Operativi

### Avvio scraping da UI

1. Browser utente apre `/`.
2. JavaScript chiama `POST /api/avvia`.
3. `indexController` delega a `ScraperPresenter`.
4. `ScraperPresenter` apre un thread daemon.
5. Nel thread viene eseguito `scraper().main()`.
6. La UI chiama periodicamente `GET /api/stato`.
7. I dati finali vengono letti da `GET /api/dati` o scaricati da `GET /api/scarica-excel`.

### Processing di un portale

1. `scraperService` carica un `Portale`.
2. `EsecutoreLoginService` verifica cookie o fa login.
3. Se login fallisce, il portale produce risultato vuoto.
4. Se login riesce, `ScrapingBandiPortaleService` naviga alla sezione bandi.
5. `ProfilatoreBandiPortaleService` usa cache o LLM discovery.
6. Se selettori validi, `EstrattoreCssService` estrae in fast track.
7. Se fast track fallisce, `EstrattoreBandiService` usa LLM.
8. Per ogni dettaglio, `EstrattoreDettagliBandoService` arricchisce il bando.
9. `BandoDao` salva progressivamente l'Excel.

### Strategia fast/slow track

Fast track:

- cache valida;
- selettori presenti;
- parsing CSS produce almeno un bando.

Slow track:

- cache assente;
- cache scaduta;
- selettori non validi;
- CSS ritorna zero bandi;
- errore durante parsing CSS.

---

## 11. Error Handling e Fallback

Login:

- timeout globale: `FAILED_ERROR`;
- CAPTCHA: `FAILED_CAPTCHA`;
- OAuth/SAML: `FAILED_MANUAL`;
- MFA: `FAILED_MFA`;
- credenziali errate: `FAILED_CREDS`;
- cookie valido: `SKIPPED_COOKIE`.

Discovery bandi:

- cache JSON illeggibile: ritorna cache vuota;
- discovery LLM fallita: usa `FALLBACK_SELETTORI`;
- selettore contenitore vuoto: skip CSS e fallback LLM;
- dettaglio non apribile: mantiene il bando base.

Output:

- se un portale non produce bandi, viene scritta una riga segnaposto;
- errori di scrittura Excel vengono loggati e ritornano `False`;
- dashboard analytics mostra messaggio se Excel non esiste.

---

## 12. Note di Manutenzione

- Non inserire commenti nei file JSON: romperebbero il parsing.
- Non versionare `.env` con chiavi reali.
- Non eliminare `sessioni/` se si vuole riusare il login.
- Se un portale cambia layout, cancellare o aggiornare la relativa voce in `config/profiler_cache.json`.
- Se i prompt producono risultati instabili, intervenire nei servizi LLM dedicati, non nell'orchestratore.
- `scraperService.py` deve restare leggero: orchestration only.
- Le modifiche ai DTO hanno impatto su LLM response_format, Excel e frontend.

---

## 13. Stato del Refactor

Il refactor ha separato responsabilita' prima concentrate in `scraperService.py`:

- configurazione/logging in `scraperConfig.py`;
- cache in `profilazioneCacheService.py`;
- report in `reportScraperService.py`;
- pipeline portale in `scrapingBandiPortaleService.py`;
- profilazione portale in `profilatoreBandiPortaleService.py`;
- dettagli bando in `estrattoreDettagliBandoService.py`;
- schemi LLM in `schemaEstrazioneBandi.py`;
- parsing classificazione login in `classificazioneLoginParser.py`;
- persistenza sessioni login in `sessioneLoginService.py`.

Questo permette di intervenire su login, discovery, parsing CSS, parsing LLM o output Excel senza riaprire l'orchestratore principale.
