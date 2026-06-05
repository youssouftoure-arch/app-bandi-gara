"""
service/crawl4ai/scraperService.py
-----------------------------------
Loop principale — itera il DataFrame portali, esegue login intelligente,
poi scraping con Crawl4AI.
"""

import asyncio
import logging
import os
from dotenv import load_dotenv
from pathlib import Path

import pandas as pd

from model.enums.statoLoginEnum import LoginStatus
from model.po.portalePo import Portale
from service.crawl4ai.esecutoreLoginService import EsecutoreLoginService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

load_dotenv()

EXCEL_PATH  = Path("user e password per Operations.xlsx")
OPENAI_KEY  = os.environ.get("OPENAI_API_KEY", "")
CONCORRENZA = 3


class scraper:

    def __init__(self):
        if not OPENAI_KEY:
            raise EnvironmentError("Variabile OPENAI_API_KEY non impostata")
        self._esecutore = EsecutoreLoginService(OPENAI_KEY)

    async def main(self):
        portali = self._carica_portali()
        logger.info("Portali caricati: %d", len(portali))

        risultati = []
        for i in range(0, len(portali), CONCORRENZA):
            batch = portali[i : i + CONCORRENZA]
            batch_risultati = await asyncio.gather(
                *[self._processa_portale(p) for p in batch]
            )
            risultati.extend(batch_risultati)
            logger.info("Completati %d / %d", min(i + CONCORRENZA, len(portali)), len(portali))

        self._stampa_riepilogo(risultati)
        return risultati

    async def _processa_portale(self, portale: Portale):
        # 1. LOGIN intelligente (vision + selettori LLM + cookie reuse)
        risultato_login = await self._esecutore.esegui_login(portale)

        if not risultato_login.is_success:
            logger.warning("[%s] Login fallito: %s", portale.url, risultato_login.status.value)
            return {"portale": portale.url, "login": risultato_login.status.value, "bandi": []}

        # 2. SCRAPING con Crawl4AI usando i cookie della sessione autenticata
        bandi = await self._scrapa_bandi(portale, risultato_login.cookies_path)

        return {"portale": portale.url, "login": risultato_login.status.value, "bandi": bandi}

    async def _scrapa_bandi(self, portale: Portale, cookies_path: str) -> list:
        """
        Scraping della pagina bandi con sessione autenticata.
        I cookie del login vengono iniettati nel crawler.
        """
        import json
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

        # Carica i cookie salvati dall'EsecutoreLoginService
        cookies = []
        if cookies_path:
            try:
                cookies = json.loads(Path(cookies_path).read_text())
            except Exception as e:
                logger.warning("[%s] Cookie non caricabili: %s", portale.url, e)

        browser_cfg = BrowserConfig(headless=True)
        run_cfg = CrawlerRunConfig(
            cookies=cookies,   # sessione autenticata
        )

        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            risultato = await crawler.arun(url=portale.url, config=run_cfg)

        # TODO: aggiungere LLMExtractionStrategy per strutturare i bandi
        # Per ora restituisce il markdown grezzo
        return risultato.markdown or ""

    def _carica_portali(self) -> list[Portale]:
        df = pd.read_excel(EXCEL_PATH, header=4)
        df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
        portali = []

        print("Colonne trovate:", df.columns.tolist())
        print(df.head(3))

        for _, row in df.iterrows():
            try:
                portali.append(Portale.from_dataframe_row(row.to_dict()))
            except Exception as exc:
                logger.warning("Riga saltata: %s", exc)
        return [p for p in portali if p.is_active]

    def _stampa_riepilogo(self, risultati):
        totale   = len(risultati)
        successi = sum(1 for r in risultati if r and r.get("login") in ("success", "skipped_cookie"))
        logger.info("=" * 50)
        logger.info("Totale: %d | Successi: %d | Falliti: %d", totale, successi, totale - successi)
        logger.info("=" * 50)