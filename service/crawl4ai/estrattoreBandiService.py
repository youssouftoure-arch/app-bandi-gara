"""
service/crawl4ai/estrattoreBandiService.py
----------------------------------------------------
Gestisce l'estrazione dell'elenco dei bandi dalla pagina principale
e l'arricchimento dei dettagli navigando nei singoli URL estratti.
"""

import asyncio
import logging
from typing import Optional

from bs4 import BeautifulSoup
from openai import AsyncOpenAI
from playwright.async_api import async_playwright
from pydantic import BaseModel, Field

from model.dto.bandoDto import Bando

logger = logging.getLogger(__name__)

CONCORRENZA_DETTAGLI = 5


class ElencoBandiOutput(BaseModel):
    bandi: list[Bando] = Field(default_factory=list, description="Lista dei bandi di gara individuati nella pagina")


class DettagliBandoOutput(BaseModel):
    importo:     Optional[str] = None
    scadenza:    Optional[str] = None
    descrizione: Optional[str] = None
    categoria:   Optional[str] = None


class EstrattoreBandiService:

    def __init__(self, llm_client: AsyncOpenAI):
        self._llm = llm_client

    async def estrai_elenco(self, url_base: str, html_contenuto: str) -> list[Bando]:
        """
        Analizza l'HTML della pagina elenco tramite LLM per estrarre la lista iniziale dei bandi.
        Forza l'estrazione dell'URL di dettaglio o di un identificativo di navigazione.
        """
        logger.info("Interrogazione LLM per estrazione elenco bandi da URL base: %s", url_base)
        
        # Pulizia preliminare del DOM per risparmiare token
        soup = BeautifulSoup(html_contenuto, "html.parser")
        for tag in soup(["script", "style", "svg", "path", "footer", "nav"]):
            tag.decompose()
            
        testo_pulito = soup.get_text(separator="\n", strip=True)
        if len(testo_pulito) > 60000:
            testo_pulito = testo_pulito[:60000] + "\n...[Testo Troncato]..."

        try:
            completion = await self._llm.beta.chat.completions.parse(
                model="gpt-4o", # Modello avanzato per mappare accuratamente i link complessi
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Sei un assistente specializzato nello scraping di portali di e-procurement e bandi di gara pubblici/privati.\n"
                            "Il tuo obiettivo principale è estrarre l'elenco dei bandi presenti nella pagina.\n\n"
                            "CRITICO PER IL CAMPO 'url_dettaglio':\n"
                            "- Devi assolutamente trovare il link o l'ancora che permette di accedere al dettaglio del bando.\n"
                            "- Cerca nei tag <a> (attributo href), ma guarda anche dentro attributi 'onclick', 'data-id', o l'ID del bottone se l'URL non è immediato.\n"
                            "- Se il link è relativo (es. '/bando/123' o 'dettaglio.aspx?id=A'), inseriscilo fedelmente. Verrà normalizzato dopo.\n"
                            "- NON lasciare 'url_dettaglio' a null se nella pagina è presente un qualsiasi elemento cliccabile per aprire quel bando."
                            "ATTENZIONE: Per il campo 'url_dettaglio', non estrarre funzioni javascript o stringhe parziali. Se il link non è un URL valido o un percorso relativo (es. /bando/123), lascia il campo vuoto o imposta null."
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
            
            # Post-processing di normalizzazione degli URL estratti
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

    async def arricchisci_bandi(self, bandi: list[Bando], cookies: list[dict]) -> list[Bando]:
        """
        Prende la lista di bandi già estratti e, per quelli con un URL dettaglio valido,
        naviga la pagina profonda isolando la sessione cookie e riempie i campi vuoti tramite LLM.
        """
        bandi_da_arricchire = [b for b in bandi if b.url_dettaglio]
        
        if not bandi_da_arricchire:
            logger.info("Nessun bando con URL dettaglio valido da arricchire.")
            return bandi

        logger.info("Avvio arricchimento profondo per %d bandi (Concorrenza massima: %d)...", 
                    len(bandi_da_arricchire), CONCORRENZA_DETTAGLI)
        
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
                        viewport={"width": 1280, "height": 800}
                    )
                    if cookies:
                        await context.add_cookies(cookies)
                    
                    page = await context.new_page()
                    try:
                        logger.info("Navigazione dettaglio bando: %s", bando.url_dettaglio)
                        await page.goto(bando.url_dettaglio, timeout=25000, wait_until="domcontentloaded")
                        await asyncio.sleep(1.5)
                        
                        html_dettaglio = await page.content()
                        # CORREZIONE QUI: Usiamo l'argomento corretto 'html_dettaglio' senza abbreviazioni
                        dettagli_llm = await self._estrai_dettagli_con_llm(
                            titolo_bando=bando.titolo, 
                            html_dettaglio=html_dettaglio
                        )
                        
                        if dettagli_llm:
                            bando.importo = bando.importo or dettagli_llm.importo
                            bando.scadenza = bando.scadenza or dettagli_llm.scadenza
                            bando.descrizione = bando.descrizione or dettagli_llm.descrizione
                            bando.categoria = bando.categoria or dettagli_llm.categoria
                            logger.info("🎯 Bando arricchito con successo: %s", bando.titolo[:40])
                    except Exception as e:
                        logger.warning("Impossibile caricare o analizzare il dettaglio per '%s': %s", bando.titolo[:40], e)
                    finally:
                        await browser.close()

        await asyncio.gather(*[_processa_singolo_bando(b) for b in bandi_da_arricchire])
        return bandi

    async def _estrai_dettagli_con_llm(self, titolo_bando: str, html_dettaglio: str) -> Optional[DettagliBandoOutput]:
        """
        Invia l'HTML pulito della pagina di dettaglio all'LLM per estrarre importo, scadenza, descrizione e categoria.
        """
        soup = BeautifulSoup(html_dettaglio, "html.parser")
        for tag in soup(["script", "style", "svg", "path", "nav", "footer"]):
            tag.decompose()
        testo_pulito = soup.get_text(separator="\n", strip=True)

        if len(testo_pulito) > 50000:
            testo_pulito = testo_pulito[:50000]

        try:
            completion = await self._llm.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Sei un estrattore dati specializzato in bandi di gara pubblici e privati italiani.\n"
                            "Analizza il testo della pagina di dettaglio di un bando e restituisci i campi richiesti.\n"
                            "REGOLE:\n"
                            "- importo: valore economico del bando/appalto (es. '1.200.000,00 €'). Null se assente.\n"
                            "- scadenza: data di scadenza per la presentazione offerte. Null se assente.\n"
                            "- descrizione: breve sintesi del bando (max 3 righe). Null se non ricavabile.\n"
                            "- categoria: tipo di fornitura/servizio (es. 'Lavori', 'Servizi IT'). Null se assente.\n"
                            "Non inventare valori. Se un'informazione non è presente, restituisci null."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Bando: {titolo_bando}\n\nTesto pagina:\n{testo_pulito}",
                    },
                ],
                response_format=DettagliBandoOutput,
                temperature=0.0,
            )
            return completion.choices[0].message.parsed
        except Exception as e:
            logger.error("Errore LLM dettaglio bando: %s", e)
            return None