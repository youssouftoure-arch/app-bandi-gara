import json
import logging
from model.dto.bandoDto import Bando
from service.crawl4ai.estrattoreCssService import EstrattoreCssService
from service.crawl4ai.discoverySelettoriService import DiscoverySelettoriService

logger = logging.getLogger(__name__)

class EstrazioneDatiService:
    def __init__(self, llm_client, config_path: str = "config/selettori_portali.json"):
        self.config_path = config_path
        self.estrattore_css = EstrattoreCssService()
        self.discovery_service = DiscoverySelettoriService(llm_client, config_path)

    async def estrai_bandi(self, html: str, portale_id: str, url_base: str) -> list[Bando]:
        """Punto di ingresso principale per l'estrazione dei bandi di un portale (Flusso Ibrido)."""
        
        # 1. Carica configurazione salvata
        config_portale = self._carica_config_portale(portale_id)
        
        # Scenario A: Portale non registrato o esplicitamente non affidabile -> Andiamo in Discovery
        if not config_portale or not config_portale.get("affidabile", False):
            logger.info(f"Portale {portale_id} non pronto o non affidabile. Avvio Discovery.")
            return await self.discovery_service.scopri_e_salva_selettori(html, portale_id, url_base)
        
        # Scenario B: Configurazione presente ed affidabile -> Tentativo Deterministico CSS
        selettori = config_portale.get("selettori")
        logger.info(f"Tentativo di estrazione deterministica CSS per {portale_id}")
        bandi = self.estrattore_css.estrai_con_selettori(html, selettori, url_base)
        
        # Verifica stabilità del layout (Soglia >= 3 bandi)
        if len(bandi) >= 3:
            logger.info(f"Estrazione CSS completata con successo ({len(bandi)} bandi).")
            return bandi
            
        # Scenario C: Il layout è cambiato! Meno di 3 bandi estratti nonostante i selettori salvati
        logger.warning(f"Il layout per il portale {portale_id} potrebbe essere cambiato (Trovati solo {len(bandi)} bandi). Invalidazione e Ri-discovery.")
        
        # Invalida temporaneamente l'affidabilità nel file JSON
        self._invalida_portale(portale_id)
        
        # Trigger della ri-discovery automatica
        return await self.discovery_service.scopri_e_salva_selettori(html, portale_id, url_base)

    def _carica_config_portale(self, portale_id: str) -> dict | None:
        try:
            with open(self.config_path, "r") as f:
                data = json.load(f)
                return data.get(portale_id)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def _invalida_portale(self, portale_id: str):
        try:
            with open(self.config_path, "r") as f:
                data = json.load(f)
            if portale_id in data:
                data[portale_id]["affidabile"] = False
                with open(self.config_path, "w") as f:
                    json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Impossibile invalidare il portale {portale_id}: {e}")