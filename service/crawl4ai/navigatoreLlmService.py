import json
import logging
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

class NavigatoreLlmService:
    def __init__(self, llm_client: AsyncOpenAI):
        self._llm = llm_client

    async def trova_url_bandi(self, url_corrente: str, links: list) -> str:
        """
        Analizza la lista dei link presenti nella pagina usando GPT-4o-mini 
        per decidere quale URL porta all'elenco dei bandi/gare/procedure.
        """
        # Riduciamo il carico di token inviando solo dati essenziali (max 80 link per evitare overflow)
        link_strati = [
            {"testo": l["testo"], "href": l["href"]} 
            for l in links if l["href"] and not l["href"].startswith("javascript")
        ][:80]
        
        if not link_strati:
            return url_corrente

        prompt = f"""
        Sei l'autopilota di un web scraper di bandi di gara pubblici e privati.
        Sei appena atterrato su questa pagina: {url_corrente}
        Il tuo obiettivo è andare alla pagina che contiene l'elenco dei bandi, delle gare, delle negoziazioni o degli avvisi di appalto.
        
        Analizza questa lista di link estratti dalla pagina corrente:
        {json.dumps(link_strati, ensure_ascii=False)}
        
        Identifica il link migliore che corrisponde a diciture come:
        - "Bandi e Avvisi", "Gare e procedure", "Procedure di gara", "Bandi di gara"
        - "Negoziazioni in corso", "Bandi aperti", "Consultazioni", "Elenco bandi"
        - "Gare", "Tenders", "Opportunities", "Avvisi"
        - Nei portali come ANAS/RFI cerca voci relative ad "Area Fornitori" -> "Gare" o "Bandi".
        
        Rispondi ESCLUSIVAMENTE con un oggetto JSON valido avente questa struttura:
        {{
            "url_selezionato": "stringa dell'url completo da cliccare",
            "motivazione": "breve spiegazione del perché"
        }}
        Se nessun link sembra idoneo o ritieni che siamo già nella pagina corretta, restituisci l'url corrente ({url_corrente}).
        """
        
        try:
            response = await self._llm.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Sei un assistente tecnico esperto di scraping e navigazione web. Rispondi solo in JSON."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.0
            )
            
            risultato = json.loads(response.choices[0].message.content)
            url_scelto = risultato.get("url_selezionato", url_corrente)
            return url_scelto
        except Exception as e:
            logger.warning("Impossibile determinare il link dei bandi via LLM: %s. Resto su URL corrente.", e)
            return url_corrente
