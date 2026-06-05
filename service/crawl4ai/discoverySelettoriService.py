import json
import logging
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from model.dto.bandoDto import Bando
from model.dto.selettorePortaleDto import ConfigSelettori
from service.crawl4ai.estrattoreCssService import EstrattoreCssService

logger = logging.getLogger(__name__)

# Schema per forzare l'LLM a restituire i selettori corretti via Structured Output
class LLMDiscoveryResponse(BaseModel):
    selettori: ConfigSelettori
    spiegazione: str

class DiscoverySelettoriService:
    def __init__(self, llm_client, config_path: str = "config/selettori_portali.json"):
        self.llm_client = llm_client  # Iniettato da ScraperService (es. client OpenAI)
        self.config_path = config_path

    async def scopri_e_salva_selettori(self, html: str, portale_id: str, url_base: str) -> list[Bando]:
        """Usa l'LLM per analizzare l'HTML, trovare i selettori, testarli e salvarli se validi."""
        logger.info(f"Avvio Discovery LLM per il portale {portale_id}")
        
        # 1. Chiediamo all'LLM i selettori CSS (Idealmente passando un HTML ridotto/pulito per risparmiare token)
        selettori_proposti = await self._chiedi_selettori_a_llm(html[:100000]) # Troncamento di sicurezza es.
        
        if not selettori_proposti:
            logger.warning("L'LLM non è stato in grado di proporre dei selettori validi.")
            return await self.esegui_fallback_full_text(html)

        # 2. Testiamo immediatamente i selettori sul DOM reale tramite l'Estrattore CSS
        bandi_testati = EstrattoreCssService.estrai_con_selettori(html, selettori_proposti.model_dump(), url_base)
        conteggio = len(bandi_testati)
        
        # 3. Validazione della soglia di confidenza (>= 3 bandi)
        if conteggio >= 3:
            logger.info(f"Discovery di successo! Trovati {conteggio} bandi. Salvo la configurazione.")
            self._salva_configurazione(portale_id, url_base, selettori_proposti.model_dump(), affidabile=True, conteggio=conteggio)
            return bandi_testati
        else:
            logger.warning(f"Soglia non raggiunta ({conteggio} bandi). I selettori non sono affidabili. Fallback Full-Text.")
            # Salviamo comunque il portale come NON affidabile per evitare loop continui di discovery
            self._salva_configurazione(portale_id, url_base, selettori_proposti.model_dump(), affidabile=False, conteggio=conteggio)
            return await self.esegui_fallback_full_text(html)

    async def esegui_fallback_full_text(self, html: str) -> list[Bando]:
        """Usa l'LLM in modalità standard per estrarre direttamente i dati dal testo (Full-text fallback)."""
        logger.info("Esecuzione LLM Fallback Full-Text...")
        
        class ListaBandiOutput(BaseModel):
            bandi: list[Bando]

        try:
            # Chiamata di estrazione diretta
            completation = await self.llm_client.beta.chat.completions.parse(
                model="gpt-4o-mini", # o il modello impostato nello scraper
                messages=[
                    {"role": "system", "content": "Sei un estrattore dati specializzato in bandi di gara. Estrai tutti i bandi presenti nell'HTML."},
                    {"role": "user", "content": f"Estrai la lista dei bandi da questo HTML:\n\n{html[:80000]}"}
                ],
                response_format=ListaBandiOutput
            )
            return completation.choices[0].message.parsed.bandi
        except Exception as e:
            logger.error(f"Errore critico anche nel fallback LLM: {e}")
            return []

    async def _chiedi_selettori_a_llm(self, html_snippet: str) -> Optional[ConfigSelettori]:
        """Chiamata strutturata all'LLM per farsi restituire la configurazione dei selettori CSS."""
        try:
            completion = await self.llm_client.beta.chat.completions.parse(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "Analizza la struttura HTML e restituisci i selettori CSS precisi per estrarre la lista dei bandi. I selettori dei campi interni (titolo, descrizione, ecc.) devono essere RELATIVI al contenitore del bando."},
                    {"role": "user", "content": f"Trova i selettori CSS in questo HTML:\n\n{html_snippet}"}
                ],
                response_format=LLMDiscoveryResponse
            )
            return completion.choices[0].message.parsed.selettori
        except Exception as e:
            logger.error(f"Errore durante la chiamata LLM Discovery: {e}")
            return None

    def _salva_configurazione(self, portale_id: str, url_base: str, selettori: dict, affidabile: bool, conteggio: int):
        import os
        from pathlib import Path

        # Forza la creazione della cartella config/ se non esiste nel container
        path_file = Path(self.config_path)
        path_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            if path_file.exists():
                with open(path_file, "r") as f:
                    data = json.load(f)
            else:
                data = {}
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}

        data[portale_id] = {
            "portale_id": portale_id,
            "url_base": url_base,
            "scoperto_il": datetime.now().strftime("%Y-%m-%d"),
            "affidabile": affidabile,
            "selettori": selettori,
            "ultimo_test": datetime.now().strftime("%Y-%m-%d"),
            "bandi_estratti_ultimo_test": conteggio
        }

        try:
            with open(path_file, "w") as f:
                json.dump(data, f, indent=2)
            logger.info(f"Configurazione salvata correttamente in {self.config_path}")
        except Exception as e:
            logger.error(f"Errore durante la scrittura del file JSON config: {e}")