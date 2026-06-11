"""Estrattore dettagli bando: arricchisce un bando interrogando l'LLM sul dettaglio."""

import logging
from typing import Optional

from bs4 import BeautifulSoup
from openai import AsyncOpenAI

from model.dto.bandoDto import Bando
from service.crawl4ai.schemaEstrazioneBandi import DettagliBandoOutput


class EstrattoreDettagliBandoService:
    def __init__(self, llm_client: AsyncOpenAI, logger: logging.Logger = None):
        self._llm = llm_client
        self._logger = logger or logging.getLogger(__name__)

    async def estrai_dati_da_dettaglio(self, bando: Bando, html_dettaglio: str, url_dettaglio: str) -> Bando:
        """
        Metodo ottimizzato per il flusso centralizzato di ScraperService.
        Prende l'HTML della pagina di dettaglio gia aperta, interroga l'LLM economico (gpt-4o-mini)
        ed estrae verticalmente l'importo economico, CIG, scadenze e categorie sovrascrivendo l'oggetto bando.
        """
        self._logger.info("Estrazione verticale dettagli tramite LLM per il bando: %s", bando.titolo[:50])

        dettagli_llm = await self.estrai_dettagli_con_llm(
            titolo_bando=bando.titolo,
            html_dettaglio=html_dettaglio,
        )

        if dettagli_llm:
            bando.importo = dettagli_llm.importo or bando.importo
            bando.scadenza = dettagli_llm.scadenza or bando.scadenza
            bando.descrizione = dettagli_llm.descrizione or bando.descrizione
            bando.categoria = dettagli_llm.categoria or bando.categoria
            self._logger.info("[Dettaglio] Dati estratti con successo per: %s -> Importo: %s", bando.titolo[:40], bando.importo)
        else:
            self._logger.warning("L'estrazione dettagli con LLM ha restituito un valore vuoto per: %s", bando.titolo[:40])

        return bando

    async def estrai_dettagli_con_llm(self, titolo_bando: str, html_dettaglio: str) -> Optional[DettagliBandoOutput]:
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
            self._logger.error("Errore LLM dettaglio bando: %s", e)
            return None
