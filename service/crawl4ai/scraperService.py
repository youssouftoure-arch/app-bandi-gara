import asyncio
import json
import logging
import os
import inspect
from dotenv import load_dotenv
from pathlib import Path
import time
import pandas as pd
from openai import AsyncOpenAI
from playwright.async_api import async_playwright

from model.enums.statoLoginEnum import LoginStatus
from model.po.portalePo import Portale
from model.dto.bandoDto import Bando

# Import del servizio di login
from service.crawl4ai.esecutoreLoginService import EsecutoreLoginService

# Import Unificato dell'Estrattore
from service.crawl4ai.estrattoreBandiService import EstrattoreBandiService

# Nome del file in cui verranno salvati i log
LOG_FILE_PATH = "scraper_activity.log"

# Configurazione del logger principale
logger = logging.getLogger()
logger.setLevel(logging.INFO)

log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s")

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)

file_handler = logging.FileHandler(LOG_FILE_PATH, mode="a", encoding="utf-8")
file_handler.setFormatter(log_formatter)
logger.addHandler(file_handler)

logger = logging.getLogger(__name__)

load_dotenv()

EXCEL_PATH  = Path("user e password per Operations.xlsx")
OPENAI_KEY  = os.environ.get("OPENAI_API_KEY", "")
CONCORRENZA = 3


class scraper:

    def __init__(self):
        if not OPENAI_KEY:
            raise EnvironmentError("Variabile OPENAI_API_KEY non impostata")
        self.llm_client = AsyncOpenAI(api_key=OPENAI_KEY)
        self._esecutore = EsecutoreLoginService(OPENAI_KEY)
        
        # Servizio Unificato per elenco e arricchimento dettagli
        self._estrattore_service = EstrattoreBandiService(llm_client=self.llm_client)

    async def main(self):
        tempo_inizio = time.time()
        
        portali = self._carica_portali()
        logger.info("Portali caricati finali attivi: %d", len(portali))

        risultati = []
        for i in range(0, len(portali), CONCORRENZA):
            batch = portali[i : i + CONCORRENZA]
            batch_risultati = await asyncio.gather(
                *[self._processa_portale(p) for p in batch]
            )
            risultati.extend(batch_risultati)
            logger.info("Completati %d / %d", min(i + CONCORRENZA, len(portali)), len(portali))

        tempo_totale = time.time() - tempo_inizio

        self._stampa_riepilogo(risultati, tempo_totale)
        self._salva_bandi_su_excel(risultati)
        
        return risultati

    async def _processa_portale(self, portale: Portale):
        try:
            risultato_login = await self._esecutore.esegui_login(portale)
        except (asyncio.CancelledError, Exception) as e:
            logger.error("[%s] Errore non gestito durante il login: %s", portale.url, e)
            return {"portale": portale.url, "login": "failed_error", "bandi": []}

        if not risultato_login.is_success:
            logger.warning("[%s] Login fallito: %s", portale.url, risultato_login.status.value)
            return {"portale": portale.url, "login": risultato_login.status.value, "bandi": []}

        try:
            bandi_estratti: list[Bando] = await self._scrapa_e_estrai_bandi(
                portale, risultato_login.cookies_path
            )
        except (asyncio.CancelledError, Exception) as e:
            logger.error("[%s] Errore non gestito durante lo scraping: %s", portale.url, e)
            return {"portale": portale.url, "login": risultato_login.status.value, "bandi": []}

        if bandi_estratti:
            self._stampa_bandi(portale.url, bandi_estratti)

        bandi_dict = [b.model_dump() for b in bandi_estratti]
        return {
            "portale": portale.url,
            "login": risultato_login.status.value,
            "bandi": bandi_dict,
            "conteggio_bandi": len(bandi_dict),
        }

    async def _scrapa_e_estrai_bandi(self, portale: Portale, cookies_path: str) -> list[Bando]:
        cookies = []
        if cookies_path:
            try:
                cookies = json.loads(Path(cookies_path).read_text())
            except Exception as e:
                logger.warning("[%s] Cookie non caricabili: %s", portale.url, e)

        # ── FASE 1: Fetch della Home Page post-login ───────────────────────
        html_contenuto = ""
        url_base = portale.url_scraping
        
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context()
                if cookies:
                    await context.add_cookies(cookies)

                page = await context.new_page()
                logger.info("[%s] Navigazione verso la Home di partenza: %s", portale.url, url_base)
                await page.goto(url_base, timeout=45_000, wait_until="networkidle")
                
                # Sotto-Fase: Caccia al link dei Bandi / Gare
                # Estraiamo tutti i link visibili nella home per farli analizzare all'LLM
                links_pagine = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('a')).map(a => ({
                        testo: a.innerText.trim(),
                        href: a.href,
                        id: a.id,
                        classe: a.className
                    })).filter(l => l.testo.length > 2 || l.href);
                }""")
                
                # Chiediamo all'LLM quale di questi link porta alla sezione "Bandi", "Gare" o "Avvisi"
                url_sezione_bandi = await self._trova_url_bandi_con_llm(url_base, links_pagine)
                
                if url_sezione_bandi and url_sezione_bandi != url_base:
                    logger.info("[%s] 🧭 IA ha deciso di navigare verso la sezione bandi: %s", portale.url, url_sezione_bandi)
                    await page.goto(url_sezione_bandi, timeout=45_000, wait_until="domcontentloaded")
                    # Diamo tempo a eventuali tabelle dinamiche di caricarsi
                    await page.wait_for_timeout(4000) 
                else:
                    logger.info("[%s] L'IA ritiene di essere già sulla pagina corretta o nessun link valido trovato.", portale.url)
                    # Forziamo una piccola attesa nel caso in cui i dati compaiano in differita via JS
                    await page.wait_for_timeout(3000)

                try:
                    await page.wait_for_selector(
                        "table tr, .bando, .gara, [class*='bando'], [class*='gara'], "
                        "[class*='tender'], [class*='appalto'], [class*='lot']",
                        timeout=5000,
                    )
                except Exception:
                    pass

                html_contenuto = await page.content()
                # Aggiorniamo l'url_base corrente con quello in cui ci troviamo effettivamente
                url_base = page.url
                await browser.close()
                
            except Exception as e:
                logger.error("[%s] Errore Playwright durante fetch/navigazione: %s", portale.url, e)
                return []

        if not html_contenuto:
            logger.warning("[%s] Contenuto HTML vuoto.", portale.url)
            return []

        # ── FASE 2: Estrazione elenco iniziale ──────────────────────────────
        try:
            # Passiamo l'URL effettivo ottenuto dopo l'eventuale navigazione guidata
            bandi = await self._estrattore_service.estrai_elenco(url_base=url_base, html_contenuto=html_contenuto)
            
            if not isinstance(bandi, list):
                logger.warning("[%s] Il risultato estratto non è una lista valida.", portale.url)
                bandi = []
                
        except Exception as e:
            logger.error("[%s] Errore nel servizio di estrazione elenco: %s", portale.url, e)
            return []

        if not bandi:
            return []

        # ── FASE 3: Arricchimento dettagli ──────────────────────────────────
        try:
            bandi = await self._estrattore_service.arricchisci_bandi(bandi, cookies)
        except Exception as e:
            logger.warning("[%s] Arricchimento dettagli fallito (dati parziali): %s", portale.url, e)

        return bandi

    def _stampa_bandi(self, url_portale: str, bandi: list[Bando]):
        print("\n" + "#" * 60)
        print(f" 🎯 BANDI ESTRATTI CON SUCCESSO DA: {url_portale}")
        print("#" * 60)
        for idx, bando in enumerate(bandi, 1):
            print(f" [{idx}] TITOLO:    {bando.titolo}")
            print(f"     SCADENZA:  {bando.scadenza or 'N/D'}")
            print(f"     IMPORTO:   {bando.importo or 'N/D'}")
            print(f"     URL DETT:  {bando.url_dettaglio or 'N/D'}")
            print("-" * 50)
        print("#" * 60 + "\n")

    def _carica_portali(self) -> list[Portale]:
        df = pd.read_excel(EXCEL_PATH, header=4)
        df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
        
        portali = []
        logger.info("Colonne trovate nell'Excel (riga 5): %s", df.columns.tolist())
        
        for _, row in df.iterrows():
            if row.isnull().all():
                continue
                
            try:
                portali.append(Portale.from_dataframe_row(row.to_dict()))
            except Exception as exc:
                logger.warning("Riga dell'Excel saltata per errore di validazione: %s", exc)
                
        return [p for p in portali if p.is_active]

    def _stampa_riepilogo(self, risultati, tempo_totale):
        # Supporta sia il caso in cui 'risultati' sia un dizionario mappato per URL, sia una lista
        lista_valori = list(risultati.values()) if isinstance(risultati, dict) else risultati

        totale = len(lista_valori)
        successi = 0
        totale_bandi = 0

        for r in lista_valori:
            if not r or not isinstance(r, dict):
                continue
            
            # Gestione sicura del valore di login (stringa o istanza di Enum)
            stato_login = r.get("login")
            stato_str = str(stato_login).lower() if stato_login else ""
            
            if "success" in stato_str or "skipped_cookie" in stato_str:
                successi += 1
            
            bandi = r.get("bandi", [])
            if isinstance(bandi, list):
                totale_bandi += len(bandi)
        
        minuti = int(tempo_totale // 60)
        secondi = int(tempo_totale % 60)
        durata_formattata = f"{minuti}m {secondi}s" if minuti > 0 else f"{secondi}s"

        logger.info("=" * 60)
        logger.info("RILASCIO OPERAZIONI DI SCRAPING COMPLETATO")
        logger.info("Totale Portali Processati:         %d", totale)
        logger.info("Login Effettuati con Successo:     %d", successi)
        logger.info("Login Falliti:                     %d", totale - successi)
        logger.info("Totale Bandi Complessivi Estratti: %d", totale_bandi)
        logger.info("Tempo Totale Impiegato:            %s", durata_formattata)
        logger.info("=" * 60)

    def _estrai_committente_da_url(self, url):
        """Metodo di fallback per pulire l'URL e ricavare un nome committente leggibile."""
        try:
            from urllib.parse import urlparse
            dominio = urlparse(url).netloc.lower()
            # Rimuove i classici sotto-domini e suffissi dei portali acquisti
            for sub in ['www.', 'acquisti.', 'portale.', 'portalefornitori.', 'fornitori.', 'eprocurement.']:
                dominio = dominio.replace(sub, '')
            nome = dominio.split('.')[0]
            return nome.upper()
        except:
            return "SCONOSCIUTO"

    def _salva_bandi_su_excel(self, risultati):
        logger.info("Generazione file Excel di riepilogo bandi...")
        righe = []
        
        lista_valori = list(risultati.values()) if isinstance(risultati, dict) else risultati

        for r in lista_valori:
            if not r or not isinstance(r, dict):
                continue
                
            url_portale = r.get("portale", "Sconosciuto")
            stato_login = r.get("login", "Sconosciuto")
            if hasattr(stato_login, "value"):
                stato_login = stato_login.value
                
            # Generiamo il committente di fallback basato sull'URL del portale attuale
            committente_fallback = self._estrai_committente_da_url(url_portale)
            
            bandi = r.get("bandi", [])
            
            if not bandi:
                righe.append({
                    "Portale": url_portale, 
                    "Stato Login": stato_login,
                    "Committente": committente_fallback, # Usa il nome del portale pulito
                    "Titolo Bando": "Nessun bando estratto o login fallito",
                    "Scadenza": "-", 
                    "Importo": "-", 
                    "Categoria": "-",
                    "Descrizione": "-", 
                    "URL Dettaglio": "-",
                })
            else:
                for bando in bandi:
                    # Normalizzazione sicura dell'oggetto bando (Pydantic o dict)
                    if hasattr(bando, "model_dump"):
                        bando_dict = bando.model_dump()
                    elif hasattr(bando, "dict"):
                        bando_dict = bando.dict()
                    elif isinstance(bando, dict):
                        bando_dict = bando
                    else:
                        bando_dict = {
                            "committente": getattr(bando, "committente", None),
                            "titolo": getattr(bando, "titolo", "-"),
                            "scadenza": getattr(bando, "scadenza", "-"),
                            "importo": getattr(bando, "importo", "-"),
                            "categoria": getattr(bando, "categoria", "-"),
                            "descrizione": getattr(bando, "descrizione", "-"),
                            "url_dettaglio": getattr(bando, "url_dettaglio", "-"),
                        }

                    # --- 🛠️ BLOCCO DI PULIZIA E FILTRO INTEGRATO ---
                    
                    # 1. Escludi le righe con scadenze vecchie (es. anno 2025)
                    scadenza_bando = bando_dict.get("scadenza", "-")
                    if "2025" in str(scadenza_bando):
                        continue  # Salta direttamente questo bando e passa al prossimo

                    # 2. Pulisci preventivamente l'URL se vedi anomalie del browser / JS corporativo
                    url_dettaglio = bando_dict.get("url_dettaglio") or "-"
                    if "undefined" in str(url_dettaglio).lower() or str(url_dettaglio).strip() == "-":
                        # Fallback all'URL principale del portale se l'LLM fallisce il selettore del link
                        url_dettaglio = url_portale 

                    # -----------------------------------------------

                    # Se l'LLM ha estratto il committente usa quello, altrimenti usa il fallback dall'URL
                    committente_finale = bando_dict.get("committente") or committente_fallback

                    righe.append({
                        "Portale":       url_portale,
                        "Stato Login":   stato_login,
                        "Committente":   str(committente_finale).upper(),
                        "Titolo Bando":  bando_dict.get("titolo") or "-",
                        "Scadenza":      scadenza_bando,  # Mantiene il valore pre-filtrato
                        "Importo":       bando_dict.get("importo") or "-",
                        "Categoria":     bando_dict.get("categoria") or "-",
                        "Descrizione":   bando_dict.get("descrizione") or "-",
                        "URL Dettaglio": url_dettaglio,   # Usa la variabile corretta con il fallback applicato
                    })
                    
        if not righe:
            logger.warning("Nessun dato raccolto. Generazione file Excel annullata.")
            return

        df_output = pd.DataFrame(righe)
        output_filename = "bandi_estratti_totale.xlsx"
        try:
            df_output.to_excel(output_filename, index=False)
            logger.info("= " * 25)
            logger.info("💾 FILE SALVATO CON SUCCESSO: %s", output_filename)
            logger.info("= " * 25)
        except Exception as e:
            logger.error("Errore salvataggio Excel: %s", e)


    async def _trova_url_bandi_con_llm(self, url_corrente: str, links: list) -> str:
        """
        Analizza la lista dei link presenti nella pagina usando GPT-4o-mini 
        per decidere quale URL porta all'elenco dei bandi/gare/procedure.
        """
        # Riduciamo il carico di token inviando solo dati essenziali (max 80 link per evitare overflow)
        link_strati = [
            {"testo": l["testo"], "href": l["href"]} 
            for l in links if l["href"] and not l["href"].startswith("javascript")
        ][:80]
        
        if not link_strati:
            return url_corrente

        prompt = f"""
        Sei l'autopilota di un web scraper di bandi di gara pubblici e privati.
        Sei appena atterrato su questa pagina: {url_corrente}
        Il tuo obiettivo è andare alla pagina che contiene l'elenco dei bandi, delle gare, delle negoziazioni o degli avvisi di appalto.
        
        Analizza questa lista di link estratti dalla pagina corrente:
        {json.dumps(link_strati, ensure_ascii=False)}
        
        Identifica il link migliore che corrisponde a diciture come:
        - "Bandi e Avvisi", "Gare e procedure", "Procedure di gara", "Bandi di gara"
        - "Negoziazioni in corso", "Bandi aperti", "Consultazioni", "Elenco bandi"
        - "Gare", "Tenders", "Opportunities", "Avvisi"
        - Nei portali come ANAS/RFI cerca voci relative ad "Area Fornitori" -> "Gare" o "Bandi".
        
        Rispondi ESCLUSIVAMENTE con un oggetto JSON valido avente questa struttura:
        {{
            "url_selezionato": "stringa dell'url completo da cliccare",
            "motivazione": "breve spiegazione del perché"
        }}
        Se nessun link sembra idoneo o ritieni che siamo già nella pagina corretta, restituisci l'url corrente ({url_corrente}).
        """
        
        try:
            response = await self.llm_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Sei un assistente tecnico esperto di scraping e navigazione web. Rispondi solo in JSON."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.0
            )
            
            risultato = json.loads(response.choices[0].message.content)
            url_scelto = risultato.get("url_selezionato", url_corrente)
            return url_scelto
        except Exception as e:
            logger.warning("Impossibile determinare il link dei bandi via LLM: %s. Resto su URL corrente.", e)
            return url_corrente