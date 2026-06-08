import json
import logging
from datetime import datetime
from typing import Optional
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from model.dto.bandoDto import Bando
from model.dto.selettorePortaleDto import ConfigSelettori
from service.crawl4ai.estrattoreCssService import EstrattoreCssService

logger = logging.getLogger(__name__)


class LLMDiscoveryResponse(BaseModel):
    selettori: ConfigSelettori
    spiegazione: str


class DiscoverySelettoriService:
    def __init__(self, llm_client, config_path: str = "config/selettori_portali.json"):
        self.llm_client = llm_client
        self.config_path = config_path

    # ──────────────────────────────────────────────
    # FIX 2: Pulizia HTML — rimuove noise e link PDF
    # ──────────────────────────────────────────────
    def _pulisci_html(self, html: str) -> str:
        """Rimuove tag inutili e link a file allegati prima di passare l'HTML all'LLM."""
        soup = BeautifulSoup(html, "html.parser")

        # Rimuovi tag strutturali non rilevanti per i bandi
        for tag in soup(["script", "style", "nav", "footer", "header", "meta", "link", "noscript"]):
            tag.decompose()

        # Rimuovi link a file allegati (PDF, DOC, ZIP, XLS, ecc.)
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            if any(ext in href for ext in [".pdf", ".doc", ".docx", ".zip", ".xls", ".xlsx", ".csv", ".ppt"]):
                a.decompose()

        return str(soup)[:80000]

    # ──────────────────────────────────────────────
    # Entry point principale
    # ──────────────────────────────────────────────
    async def scopri_e_salva_selettori(self, html: str, portale_id: str, url_base: str) -> list[Bando]:
        """Usa l'LLM per analizzare l'HTML, trovare i selettori, testarli e salvarli se validi."""
        logger.info(f"Avvio Discovery LLM per il portale {portale_id}")

        # FIX 2: usa HTML pulito invece del troncamento grezzo
        html_pulito = self._pulisci_html(html)

        # FIX 1: prompt migliorato in _chiedi_selettori_a_llm
        selettori_proposti = await self._chiedi_selettori_a_llm(html_pulito)

        if not selettori_proposti:
            logger.warning("L'LLM non è stato in grado di proporre selettori validi.")
            return await self.esegui_fallback_full_text(html)

        # Testa i selettori sull'HTML originale (non troncato) per massima accuratezza
        bandi_testati = EstrattoreCssService.estrai_con_selettori(html, selettori_proposti.model_dump(), url_base)
        conteggio = len(bandi_testati)

        if conteggio >= 3:
            logger.info(f"Discovery riuscita! {conteggio} bandi trovati. Salvo configurazione.")
            self._salva_configurazione(portale_id, url_base, selettori_proposti.model_dump(), affidabile=True, conteggio=conteggio)
            return bandi_testati
        else:
            logger.warning(f"Soglia non raggiunta ({conteggio} bandi). Avvio Fallback Full-Text.")
            self._salva_configurazione(portale_id, url_base, selettori_proposti.model_dump(), affidabile=False, conteggio=conteggio)
            return await self.esegui_fallback_full_text(html)

    # ──────────────────────────────────────────────
    # FIX 4: Fallback con prompt corretto + HTML pulito
    # ──────────────────────────────────────────────
    async def esegui_fallback_full_text(self, html: str) -> list[Bando]:
        """Estrae i dati direttamente via LLM full-text quando i selettori CSS non bastano."""
        logger.info("Esecuzione LLM Fallback Full-Text...")

        class ListaBandiOutput(BaseModel):
            bandi: list[Bando]

        # FIX 2: anche il fallback usa HTML pulito
        html_pulito = self._pulisci_html(html)

        try:
            completion = await self.llm_client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        # FIX 3: prompt corretto — qui si estraggono DATI, non selettori CSS
                        "content": (
                            "Sei un estrattore dati specializzato in portali e-procurement italiani ed europei.\n"
                            "Il tuo compito è estrarre SOLO i bandi di gara presenti nell'HTML.\n\n"
                            "REGOLE CRITICHE:\n"
                            "- Estrai SOLO bandi di gara reali (appalti, forniture, servizi)\n"
                            "- Ignora completamente: allegati, PDF, news, comunicati, breadcrumb, voci di menu\n"
                            "- Il titolo deve essere un testo descrittivo, MAI un nome file (es. 'Allegato_9.pdf' NON è un bando)\n"
                            "- Estrai scadenza e importo solo se presenti come testo, NON inventarli\n"
                            "- Se la pagina non contiene bandi, restituisci una lista vuota\n"
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Estrai i bandi di gara da questo HTML:\n\n{html_pulito}",
                    },
                ],
                response_format=ListaBandiOutput,
            )
            bandi = completion.choices[0].message.parsed.bandi
            logger.info(f"Fallback Full-Text completato: {len(bandi)} bandi estratti.")
            return bandi
        except Exception as e:
            logger.error(f"Errore critico nel fallback LLM: {e}")
            return []

    # ──────────────────────────────────────────────
    # FIX 1: Prompt discovery preciso per evitare PDF/allegati
    # ──────────────────────────────────────────────
    async def _chiedi_selettori_a_llm(self, html_snippet: str) -> Optional[ConfigSelettori]:
        """Chiamata strutturata all'LLM per ottenere i selettori CSS della lista bandi."""
        try:
            completion = await self.llm_client.beta.chat.completions.parse(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Sei un esperto di scraping di portali e-procurement italiani ed europei.\n"
                            "Trova i selettori CSS per estrarre la LISTA DEI BANDI DI GARA.\n\n"
                            "REGOLE CRITICHE:\n"
                            "- Il contenitore deve selezionare SOLO righe/card di bandi reali (appalti, forniture, servizi)\n"
                            "- NON selezionare: allegati, link a PDF/DOC/ZIP, news, comunicati, voci di menu, breadcrumb\n"
                            "- I bandi hanno sempre un titolo testuale descrittivo, spesso una scadenza e un importo\n"
                            "- I selettori interni (titolo, scadenza, importo, url) devono essere RELATIVI al contenitore\n"
                            "- Se la pagina non contiene una lista bandi, restituisci selettori vuoti\n"
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Trova i selettori CSS per i bandi di gara in questo HTML:\n\n{html_snippet}",
                    },
                ],
                response_format=LLMDiscoveryResponse,
            )
            return completion.choices[0].message.parsed.selettori
        except Exception as e:
            logger.error(f"Errore durante la chiamata LLM Discovery: {e}")
            return None

    # ──────────────────────────────────────────────
    # Persistenza configurazione
    # ──────────────────────────────────────────────
    def _salva_configurazione(self, portale_id: str, url_base: str, selettori: dict, affidabile: bool, conteggio: int):
        from pathlib import Path

        path_file = Path(self.config_path)
        path_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            data = json.loads(path_file.read_text()) if path_file.exists() else {}
        except json.JSONDecodeError:
            data = {}

        data[portale_id] = {
            "portale_id": portale_id,
            "url_base": url_base,
            "scoperto_il": datetime.now().strftime("%Y-%m-%d"),
            "affidabile": affidabile,
            "selettori": selettori,
            "ultimo_test": datetime.now().strftime("%Y-%m-%d"),
            "bandi_estratti_ultimo_test": conteggio,
        }

        try:
            path_file.write_text(json.dumps(data, indent=2))
            logger.info(f"Configurazione salvata in {self.config_path}")
        except Exception as e:
            logger.error(f"Errore scrittura configurazione: {e}")