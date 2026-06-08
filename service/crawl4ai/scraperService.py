import asyncio
import json
import logging
import os
from pathlib import Path
import time
from dotenv import load_dotenv
from openai import AsyncOpenAI
from playwright.async_api import async_playwright

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
        
        # Servizi e DAOs MVP
        self.portale_dao = PortaleDao(EXCEL_PATH)
        self.bando_dao = BandoDao()
        self._navigatore_service = NavigatoreLlmService(self.llm_client)

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
            return {"portale": portale.url, "login": risultato_login.status.value if hasattr(risultato_login.status, "value") else str(risultato_login.status), "bandi": []}

        try:
            bandi_estratti: list[Bando] = await self._scrapa_e_estrai_bandi(
                portale, risultato_login.cookies_path
            )
        except (asyncio.CancelledError, Exception) as e:
            logger.error("[%s] Errore non gestito durante lo scraping: %s", portale.url, e)
            return {"portale": portale.url, "login": risultato_login.status.value if hasattr(risultato_login.status, "value") else str(risultato_login.status), "bandi": []}

        if bandi_estratti:
            self._stampa_bandi(portale.url, bandi_estratti)

        bandi_dict = [b.model_dump() for b in bandi_estratti]
        return {
            "portale": portale.url,
            "login": risultato_login.status.value if hasattr(risultato_login.status, "value") else str(risultato_login.status),
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
                from service.crawl4ai.browserFactory import BrowserFactory
                browser, context = await BrowserFactory.create_browser_and_context(p, headless=True)
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
                url_sezione_bandi = await self._navigatore_service.trova_url_bandi(url_base, links_pagine)
                
                if url_sezione_bandi and url_sezione_bandi != url_base:
                    logger.info("[%s] 🧭 IA ha deciso di navigare verso la sezione bandi: %s", portale.url, url_sezione_bandi)
                    await page.goto(url_sezione_bandi, timeout=45_000, wait_until="domcontentloaded")
                    # Diamo tempo a eventuali tabelle dinamiche di caricarsi
                    await page.wait_for_timeout(10000) 
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

    def _salva_bandi_su_excel(self, risultati):
        self.bando_dao.salva_bandi_su_excel(risultati)