"""
service/crawl4ai/estrattoreSelettoriService.py
----------------------------------------------
DOM → LLM → JSON selettori con cache su Portale.selectors_cached
"""

import json
import logging
from datetime import datetime
from typing import Optional

from openai import AsyncOpenAI

from model.po.portalePo import Portale

logger = logging.getLogger(__name__)

PROMPT_ESTRAI_SELETTORI = """
Sei un esperto di HTML. Analizza il codice HTML fornito e individua i campi del form di login.
Restituisci SOLO un oggetto JSON valido, senza markdown, senza testo extra.

Schema obbligatorio:
{
  "username_selector": "<selettore CSS del campo username/email>",
  "password_selector": "<selettore CSS del campo password>",
  "submit_selector":   "<selettore CSS del pulsante submit>",
  "confidence":        0.0
}

Regole:
- confidence è un float tra 0.0 e 1.0
- Preferisci id (#id) > name ([name=x]) > type ([type=x]) > class (.class)
- Se un campo non esiste, metti null
- Se confidence < 0.7 significa che il form è ambiguo o non trovato
""".strip()


class EstrattoreSelettoriService:

    MODEL = "gpt-4o-mini"
    CONFIDENCE_MINIMA = 0.7

    def __init__(self, api_key: str):
        self._client = AsyncOpenAI(api_key=api_key)

    async def estrai(self, portale: Portale, html: str) -> Optional[dict]:
        """
        Estrae i selettori dal DOM HTML.
        Se il portale ha già una cache valida, la restituisce direttamente.
        """
        if self._cache_valida(portale):
            logger.info("[%s] Selettori da cache", portale.url)
            return portale.selectors_cached

        selettori = await self._chiedi_llm(html)

        if selettori and selettori.get("confidence", 0) >= self.CONFIDENCE_MINIMA:
            selettori["cached_at"] = datetime.utcnow().isoformat()
            portale.selectors_cached = selettori
            logger.info("[%s] Selettori estratti e cachati (confidence=%.2f)",
                        portale.url, selettori["confidence"])
        else:
            logger.warning("[%s] Selettori non trovati o confidence bassa", portale.url)
            return None

        return selettori

    def _cache_valida(self, portale: Portale) -> bool:
        if not portale.selectors_cached:
            return False
        cached_at = portale.selectors_cached.get("cached_at")
        if not cached_at:
            return False
        try:
            eta_ore = (datetime.utcnow() - datetime.fromisoformat(cached_at)).total_seconds() / 3600
            return eta_ore < 168  # 7 giorni
        except Exception:
            return False

    async def _chiedi_llm(self, html: str) -> Optional[dict]:
        # Tronca l'HTML per non sprecare token — i form sono quasi sempre nei primi 15k char
        html_troncato = html[:15000]
        try:
            response = await self._client.chat.completions.create(
                model=self.MODEL,
                max_tokens=256,
                messages=[
                    {"role": "system", "content": PROMPT_ESTRAI_SELETTORI},
                    {"role": "user", "content": f"HTML:\n{html_troncato}"},
                ],
            )
            raw = response.choices[0].message.content or ""
            cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            return json.loads(cleaned)
        except Exception as exc:
            logger.error("Errore estrazione selettori: %s", exc)
            return None
