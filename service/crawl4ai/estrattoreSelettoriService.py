"""
service/crawl4ai/estrattoreSelettoriService.py
"""

import json
import logging
from datetime import datetime
from typing import Optional

from openai import AsyncOpenAI

from model.po.portalePo import Portale

logger = logging.getLogger(__name__)

PROMPT_ESTRAI_SELETTORI = """
Sei un esperto di web scraping e automazione browser con Playwright. Analizza il codice HTML fornito e individua i selettori CSS ottimali per i campi del form di login.
Restituisci SOLO un oggetto JSON valido, senza blocchi markdown (no ```json), senza testo extra o introduzioni.

Schema obbligatorio delle chiavi:
{
  "username": "<selettore CSS del campo username/email>",
  "password": "<selettore CSS del campo password>",
  "submit":   "<selettore CSS del pulsante di invio/accedi>",
  "confidence": 0.0
}

Regole tassative per la scelta dei selettori:
1. EVITA ASSOLUTAMENTE ID dinamici o contenenti numeri che sembrano autogenerati (es. NON USARE '#inputEmailLogin-726' o '#button-1023').
2. Se un ID contiene numeri variabili, usa i selettori di attributo parziale. Esempio: al posto di '#inputEmailLogin-726' usa 'input[id^="inputEmailLogin"]' o 'input[name="email"]'.
3. Gerarchia di preferenza per Username/Password: Attributo 'name' stabilito > Attributo 'type' standard (es. input[type="password"]) > ID statici senza numeri > Classi CSS strutturali stabili.
4. Per il pulsante 'submit', se non ha un input/button di tipo submit chiaro, prediligi selettori generici e robusti come 'button[type="submit"]', oppure filtri sul testo se supportati come 'button:has-text("Accedi")' o 'input[value="Accedi"]'.
5. Se un campo non esiste o è impossibile da determinare, imposta il suo valore a null.
6. Il campo 'confidence' deve essere un float tra 0.0 e 1.0. Imposta una confidence inferiore a 0.7 se la struttura del form appare ambigua, protetta da script complessi o se i campi non sono direttamente individuabili.
""".strip()


class EstrattoreSelettoriService:

    MODEL_FAST    = "gpt-4o-mini"
    MODEL_STRONG  = "gpt-4o"
    CONFIDENCE_MINIMA = 0.7
    # Aumentato da 15k a 40k: molti form (Zucchetti, Coupa) sono oltre i 15k caratteri
    HTML_TRONCAMENTO  = 40000

    def __init__(self, api_key: str):
        self._client = AsyncOpenAI(api_key=api_key)

    async def estrai(self, portale: Portale, html: str) -> Optional[dict]:
        if self._cache_valida(portale):
            logger.info("[%s] Selettori da cache", portale.url)
            return portale.selectors_cached

        # Tentativo 1: modello veloce
        selettori = await self._chiedi_llm(html, self.MODEL_FAST)

        # Tentativo 2: fallback al modello forte se confidence bassa
        if not selettori or selettori.get("confidence", 0) < self.CONFIDENCE_MINIMA:
            logger.info("[%s] Confidence bassa con %s — fallback a %s",
                        portale.url, self.MODEL_FAST, self.MODEL_STRONG)
            selettori = await self._chiedi_llm(html, self.MODEL_STRONG)

        if selettori and selettori.get("confidence", 0) >= self.CONFIDENCE_MINIMA:
            selettori["cached_at"] = datetime.utcnow().isoformat()
            portale.selectors_cached = selettori
            logger.info("[%s] Selettori estratti e cachati (confidence=%.2f)",
                        portale.url, selettori["confidence"])
            return selettori

        logger.warning("[%s] Selettori non trovati o confidence bassa", portale.url)
        return None

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

    async def _chiedi_llm(self, html: str, model: str) -> Optional[dict]:
        html_troncato = html[:self.HTML_TRONCAMENTO]
        try:
            response = await self._client.chat.completions.create(
                model=model,
                max_tokens=256,
                messages=[
                    {"role": "system", "content": PROMPT_ESTRAI_SELETTORI},
                    {"role": "user",   "content": f"HTML:\n{html_troncato}"},
                ],
            )
            raw = response.choices[0].message.content or ""
            cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            return json.loads(cleaned)
        except Exception as exc:
            logger.error("[%s] Errore estrazione selettori: %s", model, exc)
            return None