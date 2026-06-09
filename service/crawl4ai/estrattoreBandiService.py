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
                model="gpt-4o", # Modello avanzato per mappare accuratamente i link complesses
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

    async def estrai_dati_da_dettaglio(self, bando: Bando, html_dettaglio: str, url_dettaglio: str) -> Bando:
        """
        Metodo ottimizzato per il flusso centralizzato di ScraperService.
        Prende l'HTML della pagina di dettaglio già aperta, interroga l'LLM economico (gpt-4o-mini)
        ed estrae verticalmente l'importo economico, CIG, scadenze e categorie sovrascrivendo l'oggetto bando.
        """
        logger.info("Estrazione verticale dettagli tramite LLM per il bando: %s", bando.titolo[:50])
        
        dettagli_llm = await self._estrai_dettagli_con_llm(
            titolo_bando=bando.titolo, 
            html_dettaglio=html_dettaglio
        )
        
        if dettagli_llm:
            # Sovrascriviamo o arricchiamo i campi del DTO Bando
            bando.importo = dettagli_llm.importo or bando.importo
            bando.scadenza = dettagli_llm.scadenza or bando.scadenza
            bando.descrizione = dettagli_llm.descrizione or bando.descrizione
            bando.categoria = dettagli_llm.categoria or bando.categoria
            logger.info("🎯 [Dettaglio] Dati estratti con successo per: %s -> Importo: %s", bando.titolo[:40], bando.importo)
        else:
            logger.warning("L'estrazione dettagli con LLM ha restituito un valore vuoto per: %s", bando.titolo[:40])
            
        return bando

    async def arricchisci_bandi(self, bandi: list[Bando], cookies: list[dict]) -> list[Bando]:
        """
        Metodo in modalità batch asincrona asettica (mantenuto per retrocompatibilità).
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
                        bando_aggiornato = await self.estrai_dati_da_dettaglio(
                            bando=bando,
                            html_dettaglio=html_dettaglio,
                            url_dettaglio=bando.url_dettaglio
                        )
                        bando = bando_aggiornato
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
                model="gpt-4o-mini",  # Ottimo connubio tra velocità ed economia per pagine singole verticali
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Sei un estrattore dati specializzato in bandi di gara pubblici e privati italiani.\n"
                            "Analizza il testo della pagina di dettaglio di un bando e restituisci i campi richiesti.\n"
                            "REGOLE RIGIDE PER L'IMPORTO:\n"
                            "- Identifica il valore economico complessivo o l'importo totale a base d'asta.\n"
                            "- Cerca simboli come '€', 'EUR' o diciture come 'valore stimato', 'importo complessivo', 'lotto unico'.\n"
                            "- Restituisci la stringa dell'importo ben formattata (es. '1.200.000,00 €'). Se assente, rispondi null.\n\n"
                            "ALTRI CAMPI:\n"
                            "- scadenza: data di scadenza per la presentazione offerte (es. 'DD/MM/YYYY'). Null se assente.\n"
                            "- descrizione: breve sintesi dell'oggetto dell'appalto (max 3 righe). Null se non ricavabile.\n"
                            "- categoria: tipo di fornitura/servizio (es. 'Lavori', 'Servizi IT', 'Forniture'). Null se assente.\n"
                            "Non inventare valori. Se un'informazione non è presente nel testo, restituisci null."
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