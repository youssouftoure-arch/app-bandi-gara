"""Pipeline scraping portale: naviga con Playwright ed estrae bandi via CSS o LLM."""

import json
import logging
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import async_playwright

from model.dto.bandoDto import Bando
from model.po.portalePo import Portale
from service.crawl4ai.browserFactory import BrowserFactory
from service.crawl4ai.estrattoreCssService import EstrattoreCssService
from service.crawl4ai.profilatoreBandiPortaleService import ProfilatoreBandiPortaleService


class ScrapingBandiPortaleService:
    def __init__(
        self,
        estrattore_service,
        navigatore_service,
        discovery_selettori_service,
        cache_service,
        logger: logging.Logger = None,
    ):
        self._estrattore_service = estrattore_service
        self._logger = logger or logging.getLogger(__name__)
        self._profilatore_service = ProfilatoreBandiPortaleService(
            navigatore_service=navigatore_service,
            discovery_selettori_service=discovery_selettori_service,
            cache_service=cache_service,
            logger=self._logger,
        )

    def _carica_cookies(self, portale: Portale, cookies_path: str) -> list[dict]:
        cookies = []
        if cookies_path:
            try:
                cookies = json.loads(Path(cookies_path).read_text())
            except Exception as e:
                self._logger.warning("[%s] Cookie non caricabili: %s", portale.url, e)
        return cookies

    async def _estrai_con_llm_e_dettagli(self, context, portale: Portale, url_base: str, html_contenuto: str) -> list[Bando]:
        bandi_finali: list[Bando] = []
        self._logger.info("[%s] [SLOW TRACK] Estraggo l'elenco iniziale tramite LLM...", portale.url)
        bandi_raw = await self._estrattore_service.estrai_elenco(url_base=url_base, html_contenuto=html_contenuto)

        if not bandi_raw or not isinstance(bandi_raw, list):
            self._logger.warning("[%s] Nessun bando trovato nell'elenco iniziale.", portale.url)
            return []

        self._logger.info(
            "[%s] Trovati %d bandi. Inizio la navigazione mirata nei dettagli...",
            portale.url,
            len(bandi_raw),
        )

        for idx, bando in enumerate(bandi_raw, 1):
            url_dettaglio = bando.url_dettaglio
            if url_dettaglio:
                url_dettaglio = urljoin(url_base, url_dettaglio.strip())
                bando.url_dettaglio = url_dettaglio

            if not url_dettaglio or not url_dettaglio.startswith("http"):
                self._logger.info("[%s] Nessun link dettaglio bando #%d - fallback su HTML elenco.", portale.url, idx)
                bando_arricchito = await self._estrattore_service.estrai_dati_da_dettaglio(
                    bando=bando,
                    html_dettaglio=html_contenuto,
                    url_dettaglio=url_base,
                )
                bandi_finali.append(bando_arricchito)
                continue

            self._logger.info("[%s] -> [%d/%d] Apertura pagina dettaglio: %s", portale.url, idx, len(bandi_raw), bando.titolo[:40])

            detail_page = await context.new_page()
            try:
                await detail_page.goto(url_dettaglio, timeout=30_000, wait_until="domcontentloaded")
                await detail_page.wait_for_timeout(2000)

                html_dettaglio = await detail_page.content()

                bando_arricchito = await self._estrattore_service.estrai_dati_da_dettaglio(
                    bando=bando,
                    html_dettaglio=html_dettaglio,
                    url_dettaglio=url_dettaglio,
                )
                bandi_finali.append(bando_arricchito)
            except Exception as detail_err:
                self._logger.error("[%s] Errore nell'apertura del dettaglio per bando #%d: %s", portale.url, idx, detail_err)
                bandi_finali.append(bando)
            finally:
                await detail_page.close()

        return bandi_finali

    async def scrapa_e_estrai_bandi(self, portale: Portale, cookies_path: str) -> list[Bando]:
        cookies = self._carica_cookies(portale, cookies_path)
        bandi_finali: list[Bando] = []
        url_base = portale.url_scraping

        async with async_playwright() as p:
            try:
                browser, context = await BrowserFactory.create_browser_and_context(p, headless=True)
                if cookies:
                    await context.add_cookies(cookies)

                page = await context.new_page()
                self._logger.info("[%s] Navigazione verso la Home di partenza: %s", portale.url, url_base)
                await page.goto(url_base, timeout=45_000, wait_until="networkidle")

                url_sezione_bandi, selettori_locali, cache_valida = await self._profilatore_service.ottieni_profilo(page, portale, url_base)
                await self._profilatore_service.vai_a_sezione_bandi(page, portale, url_base, url_sezione_bandi)

                str_selettore_attesa = selettori_locali.get("contenitore_bando") if selettori_locali else "table tr, .bando, .gara"
                try:
                    await page.wait_for_selector(str_selettore_attesa, timeout=5000)
                except Exception:
                    pass

                html_contenuto = await page.content()
                url_base = page.url

                if not html_contenuto:
                    self._logger.warning("[%s] Contenuto HTML vuoto.", portale.url)
                    await browser.close()
                    return []

                if cache_valida and selettori_locali:
                    self._logger.info("[%s] [FAST TRACK] Estrazione locale nativa con EstrattoreCssService (Zero LLM)...", portale.url)
                    try:
                        bandi_finali = EstrattoreCssService.estrai_con_selettori(
                            html=html_contenuto,
                            selettori=selettori_locali,
                            url_base=url_base,
                        )
                        if not bandi_finali:
                            self._logger.warning("[%s] L'estrazione CSS ha restituito 0 bandi. Passo forzatamente al LLM.", portale.url)
                            cache_valida = False
                    except Exception as err_css:
                        self._logger.error(
                            "[%s] Errore durante l'estrazione CSS locale: %s. Attivazione fallback forzato su LLM.",
                            portale.url,
                            err_css,
                        )
                        cache_valida = False

                if not cache_valida:
                    bandi_finali = await self._estrai_con_llm_e_dettagli(context, portale, url_base, html_contenuto)

                await browser.close()

            except Exception as e:
                self._logger.error("[%s] Errore Playwright durante fetch/navigazione: %s", portale.url, e)
                return []

        return bandi_finali
