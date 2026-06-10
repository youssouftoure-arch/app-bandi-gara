import asyncio
import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from openai import AsyncOpenAI
from playwright.async_api import async_playwright
from urllib.parse import urljoin

from model.enums.statoLoginEnum import LoginStatus
from model.po.portalePo import Portale
from model.dto.bandoDto import Bando

# Import dei servizi
from service.crawl4ai.esecutoreLoginService import EsecutoreLoginService
from service.crawl4ai.estrattoreBandiService import EstrattoreBandiService
from dao.portaleDao import PortaleDao
from dao.bandoDao import BandoDao
from service.crawl4ai.navigatoreLlmService import NavigatoreLlmService

# Nome del file in cui verranno salvati i log
LOG_FILE_PATH = "scraper_activity.log"

# Configurazione del logger principale
logger = logging.getLogger()
logger.setLevel(logging.INFO)

log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s")

if not logger.handlers:
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
        self._estrattore_service = EstrattoreBandiService(llm_client=self.llm_client)
        
        self.portale_dao = PortaleDao(EXCEL_PATH)
        self.bando_dao = BandoDao()
        self._navigatore_service = NavigatoreLlmService(self.llm_client)

        self._stato_lock = threading.Lock()
        self._scraper_stato = {
            "in_corso": False,
            "fase": "Inattivo",
            "totale_portali": 0,
            "portali_completati": 0,
            "login_ok": 0,
            "login_ko": 0,
            "totale_bandi": 0,
            "ultimo_aggiornamento": None,
            "metriche_finali": None
        }

    def get_stato(self) -> dict:
        """Restituisce una copia thread-safe dello stato corrente per le API HTTP o UI."""
        with self._stato_lock:
            return self._scraper_stato.copy()

    async def main(self):
        tempo_inizio = time.time()
        
        portali = self._carica_portali()
        totale_p = len(portali)
        logger.info("Portali caricati finali attivi: %d", totale_p)

        

        risultati = []
        sem = asyncio.Semaphore(CONCORRENZA)

        async def processa_con_sem(p: Portale):
            async with sem:
                res = await self._processa_portale(p)
                bandi_portale = res.get("bandi", [])
                
                with self._stato_lock:
                    risultati.append(res)
                    self._scraper_stato["portali_completati"] += 1
                    
                    stato_login = res.get("login", "")
                    stato_str = str(stato_login).lower()
                    if "success" in stato_str or "skipped_cookie" in stato_str:
                        self._scraper_stato["login_ok"] += 1
                    else:
                        self._scraper_stato["login_ko"] += 1
                    
                    self._scraper_stato["totale_bandi"] += len(bandi_portale)
                    self._scraper_stato["fase"] = f"Scraping in corso ({self._scraper_stato['portali_completati']}/{totale_p})"
                    self._scraper_stato["ultimo_aggiornamento"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # Salvataggio progressivo real-time
                self._salva_bandi(risultati)
                logger.info("Completato portale: %s (%d / %d)", p.url, len(risultati), totale_p)
                return res

        await asyncio.gather(*[processa_con_sem(p) for p in portali])

        tempo_totale = time.time() - tempo_inizio
        totale_bandi_finali = self._scraper_stato["totale_bandi"]

        # Salvataggio finale cumulativo (sovrascrive l'ultimo progressivo con la versione completa)
        self._salva_bandi(risultati)

        self._stampa_riepilogo(risultati, tempo_totale)
        
        return {
            "risultati": risultati,
            "metriche": {
                "totale_portali": len(risultati),
                "login_ok": self._scraper_stato["login_ok"],
                "login_ko": self._scraper_stato["login_ko"],
                "totale_bandi": totale_bandi_finali
            }
        }

    def _esegui_scraping_background(self):
        """Metodo sincrono lanciato dal thread in background per far girare il loop asincrono."""
        with self._stato_lock:
            self._scraper_stato["in_corso"] = True
            self._scraper_stato["metriche_finali"] = None  # Forza la sparizione del secondo div all'istante
            self._scraper_stato["fase"] = "Inizializzazione sessione asincrona..."
            self._scraper_stato["ultimo_aggiornamento"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Svuota il file Excel prima di iniziare il nuovo ciclo
        self.bando_dao.salva_bandi([])
        
        start_time = time.time()
        try:
            print("[Presenter] Avvio dell'Event Loop isolato con asyncio.run su self.main()...")
            risultati_raw = asyncio.run(self.main())
            
            elapsed_time = time.time() - start_time
            minuti = int(elapsed_time // 60)
            secondi = int(elapsed_time % 60)
            tempo_str = f"{minuti}m {secondi}s" if minuti > 0 else f"{secondi}s"

            with self._stato_lock:
                # Popola sempre metriche_finali con i dati reali del ciclo appena concluso.
                # Il frontend usa questo oggetto come unica fonte di verità per il div di riepilogo.
                metriche = {
                    "totale_portali": self._scraper_stato["totale_portali"],
                    "login_ok": self._scraper_stato["login_ok"],
                    "login_ko": self._scraper_stato["login_ko"],
                    "totale_bandi": self._scraper_stato["totale_bandi"],
                    "tempo_impiegato": tempo_str,
                    "file_excel": str(getattr(self.bando_dao, 'excel_path', EXCEL_PATH))
                }
                self._scraper_stato["metriche_finali"] = metriche
                self._scraper_stato["fase"] = "Completato"
                
                self._scraper_stato["ultimo_aggiornamento"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
        except Exception as e:
            print(f"[Presenter] Errore critico nello scraping in background: {e}")
            import traceback
            traceback.print_exc()
            
            with self._stato_lock:
                self._scraper_stato["fase"] = f"Errore: {str(e)}"
                self._scraper_stato["ultimo_aggiornamento"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        finally:
            with self._stato_lock:
                self._scraper_stato["in_corso"] = False

    async def _scrapa_e_estrai_bandi(self, portale: Portale, cookies_path: str) -> list[Bando]:
        cookies = []
        if cookies_path:
            try:
                cookies = json.loads(Path(cookies_path).read_text())
            except Exception as e:
                logger.warning("[%s] Cookie non caricabili: %s", portale.url, e)

        bandi_finali: list[Bando] = []
        url_base = portale.url_scraping
        
        async with async_playwright() as p:
            try:
                from service.crawl4ai.browserFactory import BrowserFactory
                browser, context = await BrowserFactory.create_browser_and_context(p, headless=True)
                if cookies:
                    await context.add_cookies(cookies)

                page = await context.new_page()
                logger.info("[%s] Navigazione verso la Home di partenza: %s", portale.url, url_base)
                await page.goto(url_base, timeout=45_000, wait_until="networkidle")
                
                links_pagine = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('a')).map(a => ({
                        testo: a.innerText.trim(),
                        href: a.href,
                        id: a.id,
                        classe: a.className
                    })).filter(l => l.testo.length > 2 || l.href);
                }""")
                
                url_sezione_bandi = await self._navigatore_service.trova_url_bandi(url_base, links_pagine)
                
                if url_sezione_bandi and url_sezione_bandi != url_base:
                    logger.info("[%s] 🧭 IA ha deciso di navigare verso la sezione bandi: %s", portale.url, url_sezione_bandi)
                    await page.goto(url_sezione_bandi, timeout=45_000, wait_until="domcontentloaded")
                    await page.wait_for_timeout(10000) 
                else:
                    logger.info("[%s] L'IA ritiene di essere già sulla pagina corretta.", portale.url)
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
                url_base = page.url

                if not html_contenuto:
                    logger.warning("[%s] Contenuto HTML vuoto.", portale.url)
                    await browser.close()
                    return []

                logger.info("[%s] Estraggo l'elenco dei bandi per raccogliere i link di dettaglio...", portale.url)
                bandi_raw = await self._estrattore_service.estrai_elenco(url_base=url_base, html_contenuto=html_contenuto)
                
                if not bandi_raw or not isinstance(bandi_raw, list):
                    logger.warning("[%s] Nessun bando trovato nell'elenco iniziale.", portale.url)
                    await browser.close()
                    return []

                logger.info("[%s] 🔍 Trovati %d bandi. Inizio la navigazione mirata nei dettagli...", portale.url, len(bandi_raw))
                
                for idx, bando in enumerate(bandi_raw, 1):
                    url_dettaglio = bando.url_dettaglio
                    if url_dettaglio:
                        url_dettaglio = urljoin(url_base, url_dettaglio.strip())
                        bando.url_dettaglio = url_dettaglio
                    
                    if not url_dettaglio or not url_dettaglio.startswith("http"):
                        logger.info("[%s] Nessun link dettaglio bando #%d - fallback su HTML elenco.", portale.url, idx)
                        bando_arricchito = await self._estrattore_service.estrai_dati_da_dettaglio(
                            bando=bando,
                            html_dettaglio=html_contenuto,
                            url_dettaglio=url_base
                        )
                        bandi_finali.append(bando_arricchito)
                        continue

                    logger.info("[%s] -> [%d/%d] Apertura pagina dettaglio: %s", portale.url, idx, len(bandi_raw), bando.titolo[:40])
                    
                    detail_page = await context.new_page()
                    try:
                        await detail_page.goto(url_dettaglio, timeout=30_000, wait_until="domcontentloaded")
                        await detail_page.wait_for_timeout(2000)
                        
                        html_dettaglio = await detail_page.content()
                        
                        bando_arricchito = await self._estrattore_service.estrai_dati_da_dettaglio(
                            bando=bando, 
                            html_dettaglio=html_dettaglio, 
                            url_dettaglio=url_dettaglio
                        )
                        bandi_finali.append(bando_arricchito)
                    except Exception as detail_err:
                        logger.error("[%s] Errore nell'apertura del dettaglio per bando #%d: %s", portale.url, idx, detail_err)
                        bandi_finali.append(bando)
                    finally:
                        await detail_page.close()

                await browser.close()
                
            except Exception as e:
                logger.error("[%s] Errore Playwright durante fetch/navigazione: %s", portale.url, e)
                return []

        return bandi_finali

    async def _processa_portale(self, portale: Portale):
        try:
            risultato_login = await self._esecutore.esegui_login(portale)
        except (asyncio.CancelledError, Exception) as e:
            logger.error("[%s] Errore non gestito durante il login: %s", portale.url, e)
            return {"portale": portale.url, "login": "failed_error", "bandi": []}

        if not risultato_login.is_success:
            stato_fallito = risultato_login.status.value if hasattr(risultato_login.status, "value") else str(risultato_login.status)
            logger.warning("[%s] Login fallito: %s", portale.url, stato_fallito)
            return {"portale": portale.url, "login": stato_fallito, "bandi": []}

        try:
            bandi_estratti: list[Bando] = await self._scrapa_e_estrai_bandi(
                portale, risultato_login.cookies_path
            )
        except (asyncio.CancelledError, Exception) as e:
            logger.error("[%s] Errore non gestito durante lo scraping: %s", portale.url, e)
            return {"portale": portale.url, "login": risultato_login.status.value if hasattr(risultato_login.status, "value") else str(risultato_login.status), "bandi": []}

        if bandi_estratti:
            self._stampa_bandi(portale.url, bandi_estratti)

        bandi_dict = [b.model_dump() if hasattr(b, 'model_dump') else b.__dict__ for b in bandi_estratti]
        return {
            "portale": portale.url,
            "login": risultato_login.status.value if hasattr(risultato_login.status, "value") else str(risultato_login.status),
            "bandi": bandi_dict,
            "conteggio_bandi": len(bandi_dict),
        }

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
        return self.portale_dao.carica_portali()

    def _stampa_riepilogo(self, risultati, tempo_totale):
        lista_valori = list(risultati.values()) if isinstance(risultati, dict) else risultati
        totale = len(lista_valori)
        successi = 0
        totale_bandi = 0

        for r in lista_valori:
            if not r or not isinstance(r, dict):
                continue
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

    def _salva_bandi(self, risultati):
        """Persiste i risultati completi nel file Excel tramite il DAO."""
        try:
            self.bando_dao.salva_bandi(risultati)
        except Exception as e:
            logger.error("[Scraper] Impossibile aggiornare l'Excel dei Bandi: %s", e)