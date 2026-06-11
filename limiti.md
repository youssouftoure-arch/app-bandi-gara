## Limiti Noti e Sfide Architetturali

Durante lo sviluppo e l'ottimizzazione della pipeline di scraping, sono emersi alcuni limiti strutturali legati alla natura dei portali e-procurement e all'architettura dell'applicazione. Di seguito sono documentati i principali ostacoli attualmente presenti:

### 1. Estrazione dell'Importo (Collo di Bottiglia LLM/Vision)
Il recupero dell'importo a base d'asta rappresenta una sfida complessa. Molto spesso, questo dato non è esposto nel testo o nel DOM della pagina HTML di dettaglio, ma è sepolto all'interno di allegati (es. file PDF, disciplinari di gara) o dietro a molteplici sotto-link annidati. 
* **Impatto:** Per recuperare sistematicamente questo dato, sarebbe necessario scaricare i PDF e utilizzare modelli LLM/Vision in maniera spropositata per leggerli e interpretarli. Questo farebbe esplodere i costi delle API e i tempi di esecuzione, rendendo la pipeline insostenibile.

### 2. Anomalia sui Link di Dettaglio in Dashboard
Attualmente è presente un bug di visualizzazione nella Dashboard utente riguardante il tracciamento dei link delle singole gare.
* **Impatto:** La UI non renderizza correttamente il link di destinazione (`url_dettaglio`) del bando specifico. Al suo posto, il sistema duplica e mostra per due volte l'URL base del portale (quello recuperato originariamente dal file Excel di configurazione). 

### 3. Isolamento della Sessione (Errore "Sessione Scaduta")
Quando l'utente consulta la Dashboard e clicca su un link per aprire il dettaglio di una gara nel proprio browser, il portale target restituisce quasi sempre un errore di "Sessione Scaduta" o reindirizza alla pagina di login.
* **Impatto:** Questo comportamento è dettato dal fatto che l'autenticazione ha successo solo all'interno della "sandbox" di Playwright. I cookie e i token di sessione validi risiedono nel browser headless dello scraper in background e non vengono (e non possono essere facilmente) condivisi con il browser web fisico utilizzato dall'utente.

### 4. Blocchi da Autenticazione a Più Fattori (MFA manuale)
Alcuni portali hanno implementato policy di sicurezza stringenti che impongono l'uso della Multi-Factor Authentication (MFA), richiedendo l'inserimento di un codice OTP inviato via SMS/Email o l'approvazione tramite app authenticator.
* **Impatto:** Lo scraper è progettato per funzionare come processo automatizzato e "unattended". Non avendo la possibilità di interagire con dispositivi fisici o bypassare questi sistemi di sicurezza dinamici, il login su queste piattaforme fallisce inevitabilmente senza un intervento manuale umano.