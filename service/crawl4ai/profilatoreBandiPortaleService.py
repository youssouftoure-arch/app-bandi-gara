"""Profilatore portale bandi: legge cache o scopre sezione bandi e selettori."""

import logging
from datetime import datetime, timedelta

from model.po.portalePo import Portale


FALLBACK_SELETTORI = {
    "contenitore_bando": "table tr, .bando, .gara, [class*='bando'], [class*='gara']",
    "titolo": "a, [class*='title'], [class*='titolo']",
    "descrizione": "",
    "scadenza": "[class*='scadenza'], [class*='date'], [class*='closing']",
    "importo": "[class*='importo'], [class*='valore'], [class*='price']",
    "categoria": "",
    "url_dettaglio": "a",
}


class ProfilatoreBandiPortaleService:
    def __init__(
        self,
        navigatore_service,
        discovery_selettori_service,
        cache_service,
        logger: logging.Logger = None,
    ):
        self._navigatore_service = navigatore_service
        self._discovery_selettori_service = discovery_selettori_service
        self._cache_service = cache_service
        self._logger = logger or logging.getLogger(__name__)

    def _leggi_cache_portale(self, portale: Portale, cache: dict):
        url_sezione_bandi = None
        selettori_locali = None
        cache_valida = False

        if portale.url in cache:
            dati_cache = cache[portale.url]
            try:
                last_updated = datetime.fromisoformat(dati_cache["last_updated"])
                tempo_trascorso = datetime.now() - last_updated

                if tempo_trascorso < timedelta(days=7):
                    url_sezione_bandi = dati_cache["url_sezione_bandi"]
                    selettori_locali = dati_cache.get("selettori")
                    cache_valida = True
                    self._logger.info("[%s] [CACHE HIT COMFORT] Trovati anche i selettori CSS in cache.", portale.url)
                else:
                    self._logger.info("[%s] [CACHE EXPIRED] Profilazione obsoleta. Richiesto refresh AI.", portale.url)
            except Exception as ce:
                self._logger.warning("[%s] Errore nel calcolo dei timestamp della cache: %s", portale.url, ce)

        return url_sezione_bandi, selettori_locali, cache_valida

    async def ottieni_profilo(self, page, portale: Portale, url_base: str):
        cache = self._cache_service.carica()
        url_sezione_bandi, selettori_locali, cache_valida = self._leggi_cache_portale(portale, cache)

        if cache_valida:
            return url_sezione_bandi, selettori_locali, cache_valida

        url_sezione_bandi, selettori_locali = await self._profila_portale(page, portale, url_base)
        cache[portale.url] = {
            "url_sezione_bandi": url_sezione_bandi,
            "selettori": selettori_locali,
            "last_updated": datetime.now().isoformat(),
        }
        self._cache_service.salva(cache)
        self._logger.info("[%s] [CACHE WRITE] Profilazione strutturata registrata nel file JSON.", portale.url)

        return url_sezione_bandi, selettori_locali, cache_valida

    async def _profila_portale(self, page, portale: Portale, url_base: str):
        self._logger.info("[%s] [CACHE MISS] L'IA deve profilare interamente il sito...", portale.url)

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
            await page.goto(url_sezione_bandi, timeout=45_000, wait_until="domcontentloaded")

        html_str = await page.content()

        try:
            html_pulito = self._discovery_selettori_service._pulisci_html(html_str)
            selettori_model = await self._discovery_selettori_service._chiedi_selettori_a_llm(html_pulito)

            if selettori_model:
                selettori_locali = selettori_model.model_dump()
            else:
                raise ValueError("L'LLM ha restituito None")
        except Exception as err_discovery:
            self._logger.warning(
                "[%s] Errore nel discovery automatico dei selettori (%s). Imposto fallback di sicurezza.",
                portale.url,
                err_discovery,
            )
            selettori_locali = FALLBACK_SELETTORI.copy()

        return url_sezione_bandi, selettori_locali

    async def vai_a_sezione_bandi(self, page, portale: Portale, url_base: str, url_sezione_bandi: str):
        if url_sezione_bandi and url_sezione_bandi != url_base:
            self._logger.info("[%s] Navigazione verso la sezione bandi: %s", portale.url, url_sezione_bandi)
            await page.goto(url_sezione_bandi, timeout=45_000, wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)
        else:
            self._logger.info("[%s] Navigatore posizionato sulla pagina corretta.", portale.url)
            await page.wait_for_timeout(3000)
