"""Orchestratore scraper: coordina portali, login, estrazione bandi, stato e salvataggi."""

import asyncio
import logging
import threading
import time
from datetime import datetime

from openai import AsyncOpenAI

from dao.bandoDao import BandoDao
from dao.portaleDao import PortaleDao
from model.dto.bandoDto import Bando
from model.po.portalePo import Portale
from service.crawl4ai.discoverySelettoriService import DiscoverySelettoriService
from service.crawl4ai.esecutoreLoginService import EsecutoreLoginService
from service.crawl4ai.estrattoreBandiService import EstrattoreBandiService
from service.crawl4ai.navigatoreLlmService import NavigatoreLlmService
from service.crawl4ai.profilazioneCacheService import ProfilazioneCacheService
from service.crawl4ai.reportScraperService import (
    formatta_durata,
    stampa_bandi as stampa_bandi_report,
    stampa_riepilogo as stampa_riepilogo_report,
    stato_login_success,
)
from service.crawl4ai.scraperConfig import (
    CACHE_FILE_PATH,
    CONCORRENZA,
    EXCEL_PATH,
    OPENAI_KEY,
    configura_logging,
)
from service.crawl4ai.scrapingBandiPortaleService import ScrapingBandiPortaleService


configura_logging()
logger = logging.getLogger(__name__)


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
        self._discovery_selettori_service = DiscoverySelettoriService(llm_client=self.llm_client)
        self._profilazione_cache_service = ProfilazioneCacheService(CACHE_FILE_PATH, logger)
        self._bandi_portale_service = ScrapingBandiPortaleService(
            estrattore_service=self._estrattore_service,
            navigatore_service=self._navigatore_service,
            discovery_selettori_service=self._discovery_selettori_service,
            cache_service=self._profilazione_cache_service,
            logger=logger,
        )

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
            "metriche_finali": None,
        }

    def get_stato(self) -> dict:
        """Restituisce una copia thread-safe dello stato corrente per le API HTTP o UI."""
        with self._stato_lock:
            return self._scraper_stato.copy()

    def _carica_file_cache(self) -> dict:
        return self._profilazione_cache_service.carica()

    def _salva_file_cache(self, cache_data: dict):
        self._profilazione_cache_service.salva(cache_data)

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

                    if stato_login_success(res.get("login", "")):
                        self._scraper_stato["login_ok"] += 1
                    else:
                        self._scraper_stato["login_ko"] += 1

                    self._scraper_stato["totale_bandi"] += len(bandi_portale)
                    self._scraper_stato["fase"] = f"Scraping in corso ({self._scraper_stato['portali_completati']}/{totale_p})"
                    self._scraper_stato["ultimo_aggiornamento"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                self._salva_bandi(risultati)
                logger.info("Completato portale: %s (%d / %d)", p.url, len(risultati), totale_p)
                return res

        await asyncio.gather(*[processa_con_sem(p) for p in portali])

        tempo_totale = time.time() - tempo_inizio
        totale_bandi_finali = self._scraper_stato["totale_bandi"]

        self._salva_bandi(risultati)
        self._stampa_riepilogo(risultati, tempo_totale)

        return {
            "risultati": risultati,
            "metriche": {
                "totale_portali": len(risultati),
                "login_ok": self._scraper_stato["login_ok"],
                "login_ko": self._scraper_stato["login_ko"],
                "totale_bandi": totale_bandi_finali,
            },
        }

    def _esegui_scraping_background(self):
        """Metodo sincrono lanciato dal thread in background per far girare il loop asincrono."""
        with self._stato_lock:
            self._scraper_stato["in_corso"] = True
            self._scraper_stato["metriche_finali"] = None
            self._scraper_stato["fase"] = "Inizializzazione sessione asincrona..."
            self._scraper_stato["ultimo_aggiornamento"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.bando_dao.salva_bandi([])

        start_time = time.time()
        try:
            print("[Presenter] Avvio dell'Event Loop isolato con asyncio.run su self.main()...")
            risultati_raw = asyncio.run(self.main())

            elapsed_time = time.time() - start_time
            tempo_str = formatta_durata(elapsed_time)

            with self._stato_lock:
                metriche = {
                    "totale_portali": self._scraper_stato["totale_portali"],
                    "login_ok": self._scraper_stato["login_ok"],
                    "login_ko": self._scraper_stato["login_ko"],
                    "totale_bandi": self._scraper_stato["totale_bandi"],
                    "tempo_impiegato": tempo_str,
                    "file_excel": str(getattr(self.bando_dao, "excel_path", EXCEL_PATH)),
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
        return await self._bandi_portale_service.scrapa_e_estrai_bandi(portale, cookies_path)

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
            return {
                "portale": portale.url,
                "login": risultato_login.status.value if hasattr(risultato_login.status, "value") else str(risultato_login.status),
                "bandi": [],
            }

        if bandi_estratti:
            self._stampa_bandi(portale.url, bandi_estratti)

        bandi_dict = [b.model_dump() if hasattr(b, "model_dump") else b.__dict__ for b in bandi_estratti]
        return {
            "portale": portale.url,
            "login": risultato_login.status.value if hasattr(risultato_login.status, "value") else str(risultato_login.status),
            "bandi": bandi_dict,
            "conteggio_bandi": len(bandi_dict),
        }

    def _stampa_bandi(self, url_portale: str, bandi: list[Bando]):
        stampa_bandi_report(url_portale, bandi)

    def _carica_portali(self) -> list[Portale]:
        return self.portale_dao.carica_portali()

    def _stampa_riepilogo(self, risultati, tempo_totale):
        stampa_riepilogo_report(risultati, tempo_totale, logger)

    def _salva_bandi(self, risultati):
        """Persiste i risultati completi nel file Excel tramite il DAO."""
        try:
            self.bando_dao.salva_bandi(risultati)
        except Exception as e:
            logger.error("[Scraper] Impossibile aggiornare l'Excel dei Bandi: %s", e)
