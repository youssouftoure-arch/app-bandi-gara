"""Estrattore bandi: estrae elenco LLM e mantiene il batch legacy di arricchimento."""

import asyncio
import logging
from typing import Optional

from bs4 import BeautifulSoup
from openai import AsyncOpenAI
from playwright.async_api import async_playwright

from model.dto.bandoDto import Bando
from service.crawl4ai.estrattoreDettagliBandoService import EstrattoreDettagliBandoService
from service.crawl4ai.schemaEstrazioneBandi import DettagliBandoOutput, ElencoBandiOutput

logger = logging.getLogger(__name__)

CONCORRENZA_DETTAGLI = 5


class EstrattoreBandiService:

    def __init__(self, llm_client: AsyncOpenAI):
        self._llm = llm_client
        self._dettagli_service = EstrattoreDettagliBandoService(llm_client, logger)

    async def estrai_elenco(self, url_base: str, html_contenuto: str) -> list[Bando]:
        """
        Analizza l'HTML della pagina elenco tramite LLM per estrarre la lista iniziale dei bandi.
        Forza l'estrazione dell'URL di dettaglio o di un identificativo di navigazione.
        """
        logger.info("Interrogazione LLM per estrazione elenco bandi da URL base: %s", url_base)

        soup = BeautifulSoup(html_contenuto, "html.parser")
        for tag in soup(["script", "style", "svg", "path", "footer", "nav"]):
            tag.decompose()

        testo_pulito = soup.get_text(separator="\n", strip=True)
        if len(testo_pulito) > 60000:
            testo_pulito = testo_pulito[:60000] + "\n...[Testo Troncato]..."

        try:
            completion = await self._llm.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Sei un estrattore di bandi di gara. Il tuo UNICO obiettivo è estrarre titolo e url_dettaglio di ogni bando nella pagina.\n"
                            "NON estrarre importo, scadenza o descrizione — quei dati verranno presi dalla pagina di dettaglio.\n\n"
                            "REGOLE PER url_dettaglio:\n"
                            "- Cerca href nei tag <a>, oppure attributi onclick/data-href che contengono un percorso.\n"
                            "- Se il link è relativo (es. /bando/123), inseriscilo fedelmente.\n"
                            "- Se l'URL contiene 'javascript:' o è solo '#', imposta null.\n"
                            "- Preferisci URL che portano a una pagina di dettaglio singola, non a filtri o categorie."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"URL Pagina: {url_base}\n\nTesto della pagina da analizzare:\n{testo_pulito}",
                    },
                ],
                response_format=ElencoBandiOutput,
                temperature=0.0,
            )

            risultato = completion.choices[0].message.parsed
            bandi_estratti = risultato.bandi if risultato else []

            bandi_validati = []
            for b in bandi_estratti:
                if b.titolo and b.titolo.strip():
                    if b.url_dettaglio:
                        url_pulito = b.url_dettaglio.strip()
                        if "javascript:" in url_pulito.lower() or url_pulito == "#":
                            b.url_dettaglio = None
                        else:
                            b.url_dettaglio = Bando.normalizza_url(url_pulito, url_base)
                    bandi_validati.append(b)

            logger.info("LLM ha individuato %d bandi nella pagina elenco.", len(bandi_validati))
            return bandi_validati

        except Exception as e:
            logger.error("Errore LLM durante l'estrazione dell'elenco bandi: %s", e)
            return []

    async def estrai_dati_da_dettaglio(self, bando: Bando, html_dettaglio: str, url_dettaglio: str) -> Bando:
        return await self._dettagli_service.estrai_dati_da_dettaglio(bando, html_dettaglio, url_dettaglio)

    async def arricchisci_bandi(self, bandi: list[Bando], cookies: list[dict]) -> list[Bando]:
        """
        Metodo in modalità batch asincrona asettica (mantenuto per retrocompatibilità).
        """
        bandi_da_arricchire = [b for b in bandi if b.url_dettaglio]

        if not bandi_da_arricchire:
            logger.info("Nessun bando con URL dettaglio valido da arricchire.")
            return bandi

        logger.info(
            "Avvio arricchimento profondo per %d bandi (Concorrenza massima: %d)...",
            len(bandi_da_arricchire),
            CONCORRENZA_DETTAGLI,
        )

        semaphore = asyncio.Semaphore(CONCORRENZA_DETTAGLI)

        async def _processa_singolo_bando(bando: Bando):
            async with semaphore:
                if bando.importo and bando.scadenza and bando.descrizione:
                    return

                from service.crawl4ai.browserFactory import BrowserFactory

                async with async_playwright() as p:
                    browser, context = await BrowserFactory.create_browser_and_context(
                        p,
                        headless=True,
                        viewport={"width": 1280, "height": 800},
                    )
                    if cookies:
                        await context.add_cookies(cookies)

                    page = await context.new_page()
                    try:
                        logger.info("Navigazione dettaglio bando: %s", bando.url_dettaglio)
                        await page.goto(bando.url_dettaglio, timeout=25000, wait_until="domcontentloaded")
                        await asyncio.sleep(1.5)

                        html_dettaglio = await page.content()
                        bando_aggiornato = await self.estrai_dati_da_dettaglio(
                            bando=bando,
                            html_dettaglio=html_dettaglio,
                            url_dettaglio=bando.url_dettaglio,
                        )
                        bando = bando_aggiornato
                    except Exception as e:
                        logger.warning("Impossibile caricare o analizzare il dettaglio per '%s': %s", bando.titolo[:40], e)
                    finally:
                        await browser.close()

        await asyncio.gather(*[_processa_singolo_bando(b) for b in bandi_da_arricchire])
        return bandi

    async def _estrai_dettagli_con_llm(self, titolo_bando: str, html_dettaglio: str) -> Optional[DettagliBandoOutput]:
        return await self._dettagli_service.estrai_dettagli_con_llm(titolo_bando, html_dettaglio)
